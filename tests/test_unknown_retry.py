"""
tests/test_unknown_retry.py

Coverage for the Hafele unknown-status retry flow:

  first pass (parse returned DEFAULT_STATUS_UNKNOWN):
    - 3 head-of-queue retries, exponential backoff on the SKU's next pop
    - 4th strike -> rpush to the TAIL with ``second_pass=True``, counter reset
  second pass (``second_pass=True``, parse still unknown):
    - no further retry; fall through to the Dinler fallback (last resort)
  non-unknown status:
    - item is yielded straight away, no retry, no Dinler

Backed by ``fakeredis`` for the queue and a hand-rolled fake Response for
the Scrapy parse call so the test exercises the real spider method
without needing a live Scrapling + redis + docker stack.
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

from spiders.hafele_parsing import SCRAPE_QUEUE_KEY, MAX_UNKNOWN_RETRIES


# ─── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def rc():
    return fakeredis.FakeStrictRedis(decode_responses=True)


@pytest.fixture
def spider(rc, monkeypatch):
    """A HafeleScraperSpider wired against fakeredis for its Redis ops.

    Patches ``get_redis`` in both the parsing module and the scraper
    module so every queue mutation in ``parse_product_api`` hits the
    fake instance. Also patches the master-meta lookup to return an
    empty dict so no SKU-specific metadata is required.
    """
    from spiders import hafele_scraper, hafele_parsing

    monkeypatch.setattr(hafele_scraper, "get_redis", lambda: rc)
    monkeypatch.setattr(hafele_parsing, "get_redis", lambda: rc)
    # Avoid hitting the master-meta hash
    monkeypatch.setattr(rc, "hget", lambda *a, **kw: None)

    sp = hafele_scraper.HafeleScraperSpider()
    # Spider.logger is a read-only property; patch the underlying logger
    # getter instead so tests don't rely on class state while still
    # suppressing log noise.
    import logging
    monkeypatch.setattr(
        type(sp), "logger",
        property(lambda self: logging.getLogger("test-hafele-scraper")),
    )
    return sp


def _fake_response(sku: str, body: bytes = b"<html><body>no stock data</body></html>",
                   status: int = 200, payload_override: dict | None = None):
    """Minimal duck-typed Scrapy Response the parse method understands."""
    api_url = (
        "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/"
        f"ViewProduct-GetPriceAndAvailabilityInformationPDS?SKU={sku}"
        "&ProductQuantity=20000&SynchronizationAjaxToken=1"
    )
    payload = {"url": api_url, "attempt": 0}
    if payload_override:
        payload.update(payload_override)
    resp = MagicMock()
    resp.status = status
    resp.body = body
    resp.text = body.decode("utf-8", errors="replace")
    resp.meta = {"payload": payload}
    return resp


# ─── Backoff helper ────────────────────────────────────────────────

class TestBackoffHelper:
    def test_zero_attempt_zero_sleep(self):
        from spiders.hafele_scraper import unknown_retry_backoff_seconds
        assert unknown_retry_backoff_seconds(0) == 0

    def test_exp_curve(self):
        from spiders.hafele_scraper import unknown_retry_backoff_seconds
        assert unknown_retry_backoff_seconds(1) == 1
        assert unknown_retry_backoff_seconds(2) == 2
        assert unknown_retry_backoff_seconds(3) == 4

    def test_cap_prevents_unbounded_sleep(self):
        """Belt-and-braces: even if ``unknown_attempt`` leaks higher
        than MAX_UNKNOWN_RETRIES, the cap stops a worker stalling."""
        from spiders.hafele_scraper import unknown_retry_backoff_seconds
        assert unknown_retry_backoff_seconds(50) <= 10


# ─── First-pass retries ────────────────────────────────────────────

class TestFirstPassRetries:
    def test_initial_unknown_requeues_to_head(self, spider, rc):
        """unknown_attempt 0 -> head-requeue with unknown_attempt 1."""
        resp = _fake_response(sku="12345678")
        list(spider.parse_product_api(resp))
        assert rc.llen(SCRAPE_QUEUE_KEY) == 1
        # Head of the LIFO (lpush+lpop) queue is lindex 0
        head = json.loads(rc.lindex(SCRAPE_QUEUE_KEY, 0))
        assert head["unknown_attempt"] == 1
        assert head.get("second_pass") is not True

    def test_second_unknown_bumps_counter(self, spider, rc):
        resp = _fake_response(sku="12345678", payload_override={"unknown_attempt": 1})
        list(spider.parse_product_api(resp))
        head = json.loads(rc.lindex(SCRAPE_QUEUE_KEY, 0))
        assert head["unknown_attempt"] == 2
        assert head.get("second_pass") is not True

    def test_third_unknown_bumps_counter(self, spider, rc):
        resp = _fake_response(sku="12345678", payload_override={"unknown_attempt": 2})
        list(spider.parse_product_api(resp))
        head = json.loads(rc.lindex(SCRAPE_QUEUE_KEY, 0))
        assert head["unknown_attempt"] == MAX_UNKNOWN_RETRIES  # 3
        assert head.get("second_pass") is not True

    def test_exhausted_retries_moves_to_tail_as_second_pass(self, spider, rc):
        """4th strike: rpush to tail with second_pass=True, counter reset."""
        # Pre-seed the queue with a decoy at the head so we can observe
        # that our new payload goes to the TAIL, not the head.
        rc.lpush(SCRAPE_QUEUE_KEY, json.dumps({"url": "decoy", "attempt": 0}))

        resp = _fake_response(
            sku="12345678",
            payload_override={"unknown_attempt": MAX_UNKNOWN_RETRIES},
        )
        list(spider.parse_product_api(resp))

        # Queue should have [decoy, our-second-pass-item]
        assert rc.llen(SCRAPE_QUEUE_KEY) == 2
        tail = json.loads(rc.lindex(SCRAPE_QUEUE_KEY, -1))
        assert tail["second_pass"] is True
        assert tail["unknown_attempt"] == 0  # reset
        assert "SKU=12345678" in tail["url"]
        head = json.loads(rc.lindex(SCRAPE_QUEUE_KEY, 0))
        assert head["url"] == "decoy"

    def test_first_pass_never_yields_an_item_or_dinler_request(self, spider, rc):
        """During first-pass retries, the scraper must not emit the item
        or kick off Dinler. Only queue mutations happen."""
        resp = _fake_response(sku="12345678", payload_override={"unknown_attempt": 0})
        emitted = list(spider.parse_product_api(resp))
        assert emitted == []


# ─── Second-pass behaviour ─────────────────────────────────────────

class TestSecondPass:
    def test_second_pass_still_unknown_fires_dinler(self, spider, rc):
        """second_pass=True + parse still unknown -> last-resort Dinler."""
        resp = _fake_response(
            sku="12345678",
            payload_override={"second_pass": True, "unknown_attempt": 0},
        )
        emitted = list(spider.parse_product_api(resp))

        # Nothing requeued (not another retry round)
        assert rc.llen(SCRAPE_QUEUE_KEY) == 0
        # One yielded Request pointing at Dinler
        assert len(emitted) == 1
        from scrapy import Request
        req = emitted[0]
        assert isinstance(req, Request)
        assert "dinlermobilya.com.tr/api/stock" in req.url
        # Dotted SKU in the URL — the dinler API expects XXX.XX.XXX
        assert "sku=123.45.678" in req.url
        # handle_httpstatus_all so non-200s reach parse_dinler_fallback
        assert req.meta.get("handle_httpstatus_all") is True

    def test_second_pass_recovered_yields_item_no_dinler(self, spider, rc):
        """If Hafele's second-pass attempt actually resolves stock, we
        ship the item directly and skip Dinler."""
        body = (
            """<html><body><table>
<tr class="values-tr">
  <td class="qty-available">42</td>
  <td class="requestedPackageStatus"><span class="availability-flag">stokta mevcut</span></td>
</tr>
</table></body></html>"""
        ).encode("utf-8")
        resp = _fake_response(
            sku="12345678",
            body=body,
            payload_override={"second_pass": True, "unknown_attempt": 0},
        )
        emitted = list(spider.parse_product_api(resp))
        assert rc.llen(SCRAPE_QUEUE_KEY) == 0
        assert len(emitted) == 1
        # Should be a plain dict (ProductItem.model_dump()), not a Request
        item = emitted[0]
        assert isinstance(item, dict)
        assert item["sku"] == "12345678"
        assert item["stok_durumu"] == "stokta mevcut"
        assert item["stock_amount"] == 42


# ─── Happy path: non-unknown status flows straight through ─────────

class TestNonUnknownStatus:
    def test_in_stock_yields_item_no_requeue_no_dinler(self, spider, rc):
        body = (
            """<html><body><table>
<tr class="values-tr">
  <td class="qty-available">15</td>
  <td class="requestedPackageStatus"><span class="availability-flag">stokta mevcut</span></td>
</tr>
</table></body></html>"""
        ).encode("utf-8")
        resp = _fake_response(sku="12345678", body=body)
        emitted = list(spider.parse_product_api(resp))
        assert rc.llen(SCRAPE_QUEUE_KEY) == 0
        assert len(emitted) == 1
        item = emitted[0]
        assert isinstance(item, dict)
        assert item["stok_durumu"] == "stokta mevcut"
        assert item["stock_amount"] == 15

    def test_order_only_status_yields_item_no_dinler(self, spider, rc):
        """A legit non-"mevcut" status (eg. 'istek üzerine') is a valid
        result; no retries, no Dinler."""
        body = (
            """<html><body>
<div id="productAvailabilityInformation">
  <p><span class="availability-flag">istek üzerine</span></p>
</div></body></html>"""
        ).encode("utf-8")
        resp = _fake_response(sku="12345678", body=body)
        emitted = list(spider.parse_product_api(resp))
        assert rc.llen(SCRAPE_QUEUE_KEY) == 0
        assert len(emitted) == 1
        assert emitted[0]["stok_durumu"] == "istek üzerine"


# ─── Non-200 path (untouched by the new flow) ──────────────────────

class TestNon200Status:
    def test_non_200_requeues_via_requeue_or_drop(self, spider, rc):
        """Non-200 keeps the existing application-attempt handling: it
        does NOT enter the unknown-retry flow."""
        resp = _fake_response(sku="12345678", status=503)
        emitted = list(spider.parse_product_api(resp))
        assert emitted == []
        # Legacy requeue_or_drop pushes to the queue with attempt+1
        assert rc.llen(SCRAPE_QUEUE_KEY) == 1
        p = json.loads(rc.lindex(SCRAPE_QUEUE_KEY, 0))
        assert p["attempt"] == 1
        assert "unknown_attempt" not in p
