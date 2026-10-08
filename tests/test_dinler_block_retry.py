"""
tests/test_dinler_block_retry.py

Dinler sometimes returns Cloudflare's TDM / bot-block HTML page instead
of its normal stock JSON. Previously this manifested as 52 rows with
``stok_durumu='Stok bilgisi bulunamadi'`` in the final Excel (an item
that failed Hafele's full retry chain AND Dinler's parse step).

The fix retries Dinler once with a *different* curl_cffi impersonation
profile after a short sleep. Manual curl probe confirmed Dinler's edge
is pattern-based (not IP-based), so rotating the profile reliably
clears the block without us leaking a session identifier.

This test file covers:
- The HTML-block detection heuristic (positive and negative cases)
- The profile-rotation helper's "must-be-different" contract
- ``parse_dinler_fallback`` emitting a retry Request on first block
- ``parse_dinler_fallback`` giving up (log parse_error, yield item)
  on the second block in a row — we never loop
- Normal JSON parse errors (non-block body) do NOT trigger retry
"""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock

import fakeredis
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCRAPLING_STORAGE_DIR", "/tmp")

from spiders.headers import IMPERSONATION_PROFILES
from spiders.hafele_scraper import (
    looks_like_dinler_block_page,
    pick_different_impersonation_profile,
    MAX_DINLER_BLOCK_RETRIES,
    DINLER_BLOCK_RETRY_SLEEP_SECONDS,
)


# ─── Block-page detection ──────────────────────────────────────────

class TestLooksLikeDinlerBlockPage:
    def test_turkish_block_text(self):
        body = (
            "Erişim engellendi. Otomatik veri toplama ve izinsiz "
            "kopyalama yasaktır."
        ).encode("utf-8")
        assert looks_like_dinler_block_page(body)

    def test_cloudflare_html_block(self):
        body = (
            b"<!DOCTYPE html><html><head><title>Attention Required! | Cloudflare</title>"
            b"</head></html>"
        )
        assert looks_like_dinler_block_page(body)

    def test_html_tag_alone_is_block(self):
        """A response that opens with <html> can't be the JSON API's
        reply shape, so even without the Turkish string we flag it."""
        assert looks_like_dinler_block_page(b"<html><body>whatever</body></html>")

    def test_legit_json_is_not_block(self):
        body = (
            b'{"success":true,"sku":"901.98.256","state":"in_stock",'
            b'"stockAmount":35}'
        )
        assert not looks_like_dinler_block_page(body)

    def test_empty_body_is_not_block(self):
        assert not looks_like_dinler_block_page(b"")
        assert not looks_like_dinler_block_page(None)

    def test_short_truncated_json_is_not_block(self):
        """Legit-but-malformed JSON (eg. truncated response) must NOT
        trip the block detector — those shouldn't trigger the retry."""
        assert not looks_like_dinler_block_page(b'{"success":tru')


# ─── Profile rotation ──────────────────────────────────────────────

class TestPickDifferentImpersonation:
    def test_rotates_off_previous(self):
        """Called with each known profile, the result must differ."""
        for prev in IMPERSONATION_PROFILES:
            got = pick_different_impersonation_profile(prev)
            assert got in IMPERSONATION_PROFILES
            assert got != prev

    def test_unknown_prev_returns_valid_profile(self):
        got = pick_different_impersonation_profile("mystery")
        assert got in IMPERSONATION_PROFILES

    def test_none_prev_returns_valid_profile(self):
        got = pick_different_impersonation_profile(None)
        assert got in IMPERSONATION_PROFILES


# ─── Scraper spider fixture ────────────────────────────────────────

@pytest.fixture
def rc():
    return fakeredis.FakeStrictRedis(decode_responses=True)


@pytest.fixture
def spider(rc, monkeypatch):
    from spiders import hafele_scraper, hafele_parsing
    monkeypatch.setattr(hafele_scraper, "get_redis", lambda: rc)
    monkeypatch.setattr(hafele_parsing, "get_redis", lambda: rc)
    import logging
    sp = hafele_scraper.HafeleScraperSpider()
    monkeypatch.setattr(
        type(sp), "logger",
        property(lambda self: logging.getLogger("test-dinler-block")),
    )
    # Collapse the real-sleep in retries so tests stay fast
    monkeypatch.setattr(hafele_scraper, "DINLER_BLOCK_RETRY_SLEEP_SECONDS", 0)
    return sp


def _fake_dinler_response(body: bytes, status: int = 200,
                          sku: str = "12345678",
                          dinler_block_retry: int | None = None,
                          impersonate_used: str | None = None):
    """A duck-typed Scrapy Response the Dinler-fallback callback uses."""
    resp = MagicMock()
    resp.status = status
    resp.body = body
    resp.text = body.decode("utf-8", errors="replace") if body else ""
    resp.url = f"https://www.dinlermobilya.com.tr/api/stock?sku=123.45.678&quantity=1"
    meta = {
        "item": {"sku": sku, "stock_code": sku, "stok_durumu": "Stok bilgisi bulunamadi"},
        "sku": sku,
        "handle_httpstatus_all": True,
    }
    if dinler_block_retry is not None:
        meta["dinler_block_retry"] = dinler_block_retry
    if impersonate_used is not None:
        meta["impersonate_used"] = impersonate_used
    resp.meta = meta
    return resp


# ─── parse_dinler_fallback retry flow ──────────────────────────────

class TestDinlerBlockRetryFlow:
    def test_block_page_triggers_retry_with_rotated_profile(self, spider):
        """First block: must yield a new Dinler Request with a different
        impersonation profile and incremented dinler_block_retry."""
        from scrapy import Request

        resp = _fake_dinler_response(
            body=b"<!DOCTYPE html><html>Attention Required Cloudflare</html>",
            impersonate_used="chrome",
        )
        emitted = list(spider.parse_dinler_fallback(resp))
        assert len(emitted) == 1
        req = emitted[0]
        assert isinstance(req, Request)
        assert "dinlermobilya.com.tr/api/stock" in req.url
        assert req.meta["dinler_block_retry"] == 1
        assert req.meta["impersonate_override"] in IMPERSONATION_PROFILES
        assert req.meta["impersonate_override"] != "chrome"  # rotated off
        # Item is CARRIED, not yielded on this round — it's shipped on
        # the retry attempt.
        assert req.meta["item"]["sku"] == "12345678"

    def test_second_block_gives_up_and_ships_item(self, spider):
        """Second block in a row (dinler_block_retry == 1 == MAX): we
        stop retrying, log parse_error, and yield the item unchanged."""
        html = (
            "<html>Erişim engellendi. Otomatik veri toplama "
            "yasaktır.</html>"
        ).encode("utf-8")
        resp = _fake_dinler_response(
            body=html,
            dinler_block_retry=MAX_DINLER_BLOCK_RETRIES,
            impersonate_used="firefox",
        )
        emitted = list(spider.parse_dinler_fallback(resp))
        assert len(emitted) == 1
        # Yielded a dict (item), not a Request
        item = emitted[0]
        assert isinstance(item, dict)
        assert item["sku"] == "12345678"
        # stok_durumu stays as original DEFAULT_STATUS (what the parse
        # error path preserves) — we don't invent anything
        assert item["stok_durumu"] == "Stok bilgisi bulunamadi"

    def test_bad_json_without_html_markers_no_retry(self, spider):
        """Truncated / non-HTML garbage shouldn't trigger the block
        retry — only Cloudflare-shaped HTML pages do. We just accept
        the parse failure and ship the item."""
        resp = _fake_dinler_response(
            body=b'{"success":tru',  # legit malformed JSON
            impersonate_used="chrome",
        )
        emitted = list(spider.parse_dinler_fallback(resp))
        assert len(emitted) == 1
        assert isinstance(emitted[0], dict)
        assert emitted[0]["sku"] == "12345678"

    def test_legit_json_response_no_retry_no_block_check(self, spider):
        """Happy path: valid JSON -> no retry, item updated, no Dinler
        Request yielded."""
        body = (
            b'{"success":true,"sku":"123.45.678","state":"in_stock",'
            b'"stockAmount":42,"message":"Stokta 42 Adet mevcut."}'
        )
        resp = _fake_dinler_response(body=body)
        emitted = list(spider.parse_dinler_fallback(resp))
        assert len(emitted) == 1
        item = emitted[0]
        assert isinstance(item, dict)
        assert item["stock_amount"] == 42

    def test_retry_meta_round_trip_shape(self, spider):
        """Verify every meta key the middleware + retry chain needs is
        set correctly on the yielded retry Request."""
        resp = _fake_dinler_response(
            body=b"<html>cloudflare</html>",
            impersonate_used="safari",
        )
        req = next(iter(spider.parse_dinler_fallback(resp)))
        meta = req.meta
        # Scrapy-level flags carried through
        assert meta["handle_httpstatus_all"] is True
        # Item is preserved
        assert meta["item"]["sku"] == "12345678"
        # Retry bookkeeping
        assert meta["dinler_block_retry"] == 1
        assert meta["impersonate_override"] != "safari"
        # SKU reference preserved for logging
        assert meta["sku"] == "12345678"
