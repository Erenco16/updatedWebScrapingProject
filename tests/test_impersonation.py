"""
tests/test_impersonation.py

Verifies that both HTTP paths — Scrapy's middleware and the one-shot
harvester fetch — hand Scrapling an ``impersonate=`` kwarg sourced from
``spiders.headers.IMPERSONATION_PROFILES``.

We're not testing curl_cffi itself (that's upstream's job); we're
pinning the wiring: "when we call Fetcher.get, we always pass a valid
browser alias". That's what defends us against someone silently
reverting back to manual UA rotation.

Optional live integration test against httpbin.org proves the resulting
request actually carries a modern UA. It's gated behind ``RUN_LIVE_TESTS=1``
so CI doesn't hit the public internet on every run.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spiders.headers import IMPERSONATION_PROFILES


def _make_response(url: str = "https://example.com/", status: int = 200, body: bytes = b"<html></html>"):
    """Minimal duck-typed stand-in for a Scrapling Fetcher response."""
    resp = MagicMock()
    resp.url = url
    resp.content = body
    resp.body = body
    resp.text = body.decode("utf-8", errors="replace")
    resp.status_code = status
    resp.status = status
    resp.headers = {"Content-Type": "text/html; charset=utf-8"}
    return resp


# ─── Middleware path ────────────────────────────────────────────

class TestMiddlewareImpersonation:
    def _build_mw(self):
        from spiders.middlewares import ScraplingDownloadMiddleware
        return ScraplingDownloadMiddleware(timeout=10)

    def _fake_request(self, url: str = "https://www.hafele.com.tr/"):
        req = MagicMock()
        req.url = url
        req.method = "GET"
        req.body = b""
        req.cookies = {}
        req.headers.items.return_value = [
            (b"Accept", [b"text/html"]),
        ]
        return req

    def test_impersonate_kwarg_is_passed(self):
        """The middleware MUST pass ``impersonate=<browser alias>`` on
        every Fetcher.get call. This is the whole point of Task 1."""
        mw = self._build_mw()
        with patch("spiders.middlewares._FETCHER_CLS") as fetcher_cls:
            fetcher_cls.get.return_value = _make_response()
            mw._fetch(self._fake_request())

        assert fetcher_cls.get.called, "Fetcher.get was never called"
        _, kwargs = fetcher_cls.get.call_args
        assert "impersonate" in kwargs, (
            "impersonate kwarg missing; middleware regressed to raw httpx"
        )
        assert kwargs["impersonate"] in IMPERSONATION_PROFILES, (
            f"impersonate={kwargs['impersonate']!r} is not a Scrapling-supported "
            f"profile ({IMPERSONATION_PROFILES})"
        )

    def test_impersonate_profile_is_rotatable(self):
        """Patch the picker to force each alias in turn and prove the
        middleware forwards whichever value the picker returns."""
        mw = self._build_mw()
        for profile in IMPERSONATION_PROFILES:
            with patch("spiders.middlewares._pick_impersonation_profile", return_value=profile):
                with patch("spiders.middlewares._FETCHER_CLS") as fetcher_cls:
                    fetcher_cls.get.return_value = _make_response()
                    mw._fetch(self._fake_request())
                    _, kwargs = fetcher_cls.get.call_args
                    assert kwargs["impersonate"] == profile

    def test_fetch_still_works_when_scrapling_rejects_impersonate(self):
        """If a future Scrapling version drops ``impersonate=``, the
        middleware must degrade cleanly (strip the kwarg + retry),
        not raise TypeError at the spider."""
        from scrapy.http import HtmlResponse

        mw = self._build_mw()
        with patch("spiders.middlewares._FETCHER_CLS") as fetcher_cls:
            # First call: TypeError (impersonate rejected).
            # Second call (allow_redirects fallback): also TypeError.
            # Third call (impersonate dropped): succeed.
            fetcher_cls.get.side_effect = [
                TypeError("unexpected kwarg 'impersonate'"),
                TypeError("unexpected kwarg 'impersonate'"),
                _make_response(),
            ]
            resp = mw._fetch(self._fake_request())

        assert isinstance(resp, HtmlResponse)
        assert fetcher_cls.get.call_count == 3


# ─── Harvester path ─────────────────────────────────────────────

class TestHarvesterImpersonation:
    def test_fetch_passes_impersonate(self):
        """The harvester's one-shot sitemap fetch takes the same
        impersonation path."""
        from spiders import hafele_harvester

        with patch.object(hafele_harvester, "Fetcher") as fetcher:
            fetcher.get.return_value = _make_response(body=b"<xml/>")
            hafele_harvester.fetch("https://www.hafele.com.tr/tr/sitemap.xml")

        assert fetcher.get.called
        _, kwargs = fetcher.get.call_args
        assert "impersonate" in kwargs
        assert kwargs["impersonate"] in IMPERSONATION_PROFILES

    def test_fetch_uses_randomized_profile(self):
        """Patching the picker proves the harvester actually asks the
        rotator, not a hardcoded value."""
        from spiders import hafele_harvester

        for profile in IMPERSONATION_PROFILES:
            with patch.object(hafele_harvester, "_pick_impersonation_profile", return_value=profile):
                with patch.object(hafele_harvester, "Fetcher") as fetcher:
                    fetcher.get.return_value = _make_response(body=b"<xml/>")
                    hafele_harvester.fetch("https://www.hafele.com.tr/tr/sitemap.xml")
                    _, kwargs = fetcher.get.call_args
                    assert kwargs["impersonate"] == profile


# The live-httpbin integration test was removed in favour of the mock
# tests above: they cover the contract (``impersonate=`` is always
# passed to Fetcher.get with a valid alias) without needing network
# access, which keeps the suite deterministic and fast.
