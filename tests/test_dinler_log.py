"""
tests/test_dinler_log.py

Unit coverage for the dedicated Dinler-fallback JSONL log:
- every outcome type produces a well-shaped record
- the summariser buckets outcomes and surfaces the top error signatures
- repeated errors with per-request noise (SKUs, URLs, whitespace) still
  bucket to the same signature so the "top error" table stays useful
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spiders import dinler_log


@pytest.fixture
def tmp_log(tmp_path):
    """Isolated log file + logger-handler reset per test."""
    path = str(tmp_path / "dinler_fallback.log")
    dinler_log._reset_for_tests()
    # Point default location so helpers that don't accept a path still land here
    old = os.environ.get("DINLER_LOG_PATH")
    os.environ["DINLER_LOG_PATH"] = path
    yield path
    dinler_log._reset_for_tests()
    if old is None:
        os.environ.pop("DINLER_LOG_PATH", None)
    else:
        os.environ["DINLER_LOG_PATH"] = old


# ─── log_fallback_attempt record shape ──────────────────────────

class TestLogRecord:
    def test_resolved_record_has_state_and_amount(self, tmp_log):
        dinler_log.log_fallback_attempt(
            "90198256", "resolved",
            state="in_stock", stock_amount=35,
            message="Stokta 35 Adet mevcut",
            log_path=tmp_log,
        )
        rec = _read_one(tmp_log)
        assert rec["outcome"] == "resolved"
        assert rec["sku"] == "90198256"
        assert rec["sku_dotted"] == "901.98.256"
        assert rec["state"] == "in_stock"
        assert rec["stock_amount"] == 35
        assert "ts" in rec

    def test_miss_record_captures_message(self, tmp_log):
        dinler_log.log_fallback_attempt(
            "54649432", "miss",
            message="Ürün bulunamadı",
            log_path=tmp_log,
        )
        rec = _read_one(tmp_log)
        assert rec["outcome"] == "miss"
        assert rec["message"] == "Ürün bulunamadı"
        assert rec["error_signature"] == "Ürün bulunamadı"

    def test_http_error_record_captures_status(self, tmp_log):
        dinler_log.log_fallback_attempt(
            "11111111", "http_error",
            status=503, message="service unavailable",
            log_path=tmp_log,
        )
        rec = _read_one(tmp_log)
        assert rec["outcome"] == "http_error"
        assert rec["status"] == 503

    def test_transport_error_captures_exception(self, tmp_log):
        exc = ConnectionError("Max retries exceeded with url: /api/stock")
        dinler_log.log_fallback_attempt("22222222", "transport_error", error=exc, log_path=tmp_log)
        rec = _read_one(tmp_log)
        assert rec["outcome"] == "transport_error"
        assert rec["error_class"] == "ConnectionError"
        assert "Max retries exceeded" in rec["error_signature"]


# ─── signature normalisation ────────────────────────────────────

class TestSignatureNormalization:
    def test_sku_and_url_collapse(self):
        sig = dinler_log._normalize_error_signature(
            "Timeout fetching https://www.dinlermobilya.com.tr/api/stock?sku=901.98.256"
        )
        # Both the URL and SKU should be masked so repeated failures
        # with different SKUs bucket together.
        assert "<url>" in sig
        assert "901.98.256" not in sig

    def test_whitespace_collapses(self):
        assert dinler_log._normalize_error_signature("  foo    bar\nbaz  ") == "foo bar baz"

    def test_signature_is_length_bounded(self):
        long = "x" * 1000
        assert len(dinler_log._normalize_error_signature(long)) <= 240

    def test_none_signature_is_empty(self):
        assert dinler_log._normalize_error_signature(None) == ""


# ─── summarize_log ──────────────────────────────────────────────

class TestSummarizeLog:
    def test_empty_log_summarizes_cleanly(self, tmp_path):
        """Reporter must still render a usable summary even if nothing
        ever fell through to Dinler."""
        empty_path = str(tmp_path / "nothing.log")
        summary = dinler_log.summarize_log(empty_path)
        assert summary["total_attempts"] == 0
        assert summary["unique_skus"] == 0
        assert summary["by_outcome"] == {}
        assert summary["top_error_signatures"] == []

    def test_summary_counts_outcomes_and_unique_skus(self, tmp_log):
        for sku in ("10000001", "10000002", "10000001"):  # dup
            dinler_log.log_fallback_attempt(
                sku, "resolved", state="in_stock", stock_amount=5, log_path=tmp_log,
            )
        dinler_log.log_fallback_attempt("10000003", "miss", message="not found", log_path=tmp_log)
        dinler_log.log_fallback_attempt(
            "10000004", "transport_error",
            error=TimeoutError("Connection timed out after 10s"),
            log_path=tmp_log,
        )

        summary = dinler_log.summarize_log(tmp_log)
        assert summary["total_attempts"] == 5
        assert summary["unique_skus"] == 4
        assert summary["by_outcome"] == {
            "resolved": 3, "miss": 1, "transport_error": 1,
        }

    def test_top_error_signatures_bucket_similar_errors(self, tmp_log):
        """3 different SKUs failing with the same shape of error → one
        bucket of 3, not three buckets of 1 (the whole reason signatures
        get normalised)."""
        for sku in ("10000001", "10000002", "10000003"):
            dinler_log.log_fallback_attempt(
                sku, "transport_error",
                error=ConnectionError(f"Connection refused by https://dinler/api/stock?sku={sku}"),
                log_path=tmp_log,
            )
        dinler_log.log_fallback_attempt(
            "10000004", "http_error", status=503, message="Service Unavailable",
            log_path=tmp_log,
        )

        summary = dinler_log.summarize_log(tmp_log, top_n=5)
        sigs = dict(summary["top_error_signatures"])
        # 3 ConnectionError lines should land in the same bucket
        conn_sig_count = max(v for k, v in sigs.items() if "Connection refused" in k)
        assert conn_sig_count == 3

    def test_format_summary_is_human_readable(self, tmp_log):
        dinler_log.log_fallback_attempt(
            "10000001", "resolved", state="in_stock", stock_amount=1, log_path=tmp_log,
        )
        summary = dinler_log.summarize_log(tmp_log)
        text = dinler_log.format_summary(summary)
        assert "Dinler fallback summary" in text
        assert "fallback attempts: 1" in text
        assert "unique products  : 1" in text
        assert "resolved" in text


# ─── helpers ────────────────────────────────────────────────────

def _read_one(path: str) -> dict:
    """Flush any buffered writes, return the first JSON record."""
    for h in __import__("logging").getLogger(dinler_log._LOGGER_NAME).handlers:
        try:
            h.flush()
        except Exception:
            pass
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if raw:
                return json.loads(raw)
    raise AssertionError(f"log file empty: {path}")
