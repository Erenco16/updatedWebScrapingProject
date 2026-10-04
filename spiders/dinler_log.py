"""
spiders/dinler_log.py

Dedicated, append-only JSON-lines log for every time a Hafele variant
falls through to the Dinler Mobilya stock API, plus a summariser the
reporter uses at end-of-run.

Why a separate file (and not just the main scraper log):
- Operators asked for a count of products using the fallback and the
  most common error signatures. Mining those out of the main log is
  slow and the main log rotates/truncates on container restart.
- Each scraper replica appends to the same file on the shared data
  volume. POSIX ``O_APPEND`` writes smaller than PIPE_BUF (4096 B) are
  atomic across processes; our JSON lines are well under that bound,
  so no file-locking is needed.

Record schema (one JSON object per line):
    {"ts": "<iso>", "sku": "<digits>", "sku_dotted": "<xxx.xx.xxx>",
     "outcome": "resolved" | "miss" | "transport_error" | "parse_error" | "http_error",
     "state": "<dinler state>"?,        # resolved
     "stock_amount": <int>?,            # resolved
     "message": "<text>"?,              # miss / resolved
     "status": <int>?,                  # http_error
     "error_class": "<ExceptionName>"?, # transport/parse errors
     "error_signature": "<text>"?}      # normalized, used for top-N buckets
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

from spiders.models import format_sku_with_dots

_DEFAULT_LOG_PATH = os.getenv("DINLER_LOG_PATH", "/app/data/dinler_fallback.log")

_LOGGER_NAME = "hafele.dinler_fallback"
_INIT_LOCK = threading.Lock()
_initialized = False


def _get_logger(path: str = _DEFAULT_LOG_PATH) -> logging.Logger:
    """Return the shared Dinler-fallback JSONL logger.

    Idempotent: subsequent calls with the same path reuse the handler.
    """
    global _initialized
    logger = logging.getLogger(_LOGGER_NAME)
    if _initialized:
        return logger
    with _INIT_LOCK:
        if _initialized:
            return logger
        logger.setLevel(logging.INFO)
        logger.propagate = False  # don't double-print into Scrapy's root logger
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        except OSError:
            pass
        try:
            handler = logging.FileHandler(path, mode="a", encoding="utf-8")
        except OSError:
            # Fallback to a NullHandler so logging never crashes the spider
            # (e.g. in tests or when the data volume isn't mounted).
            handler = logging.NullHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        _initialized = True
    return logger


def _reset_for_tests() -> None:
    """Drop the cached handler so tests can point the logger at a tmp path."""
    global _initialized
    with _INIT_LOCK:
        logger = logging.getLogger(_LOGGER_NAME)
        for h in list(logger.handlers):
            try:
                h.close()
            except Exception:
                pass
            logger.removeHandler(h)
        _initialized = False


_SIG_SKU_RE = re.compile(r"\b\d{3}\.\d{2}\.\d{3}\b|\b\d{6,}\b")
_SIG_WHITESPACE_RE = re.compile(r"\s+")
_SIG_URL_RE = re.compile(r"https?://\S+")


def _normalize_error_signature(text: Any) -> str:
    """Collapse per-request noise (SKUs, URLs, whitespace) out of an
    error string so repeated failures bucket together in the summary.
    """
    if text is None:
        return ""
    s = str(text).strip()
    if not s:
        return ""
    s = _SIG_URL_RE.sub("<url>", s)
    s = _SIG_SKU_RE.sub("<sku>", s)
    s = _SIG_WHITESPACE_RE.sub(" ", s)
    return s[:240]  # bound signature length for the top-N bucket


def log_fallback_attempt(
    sku: str,
    outcome: str,
    *,
    state: str | None = None,
    stock_amount: int | None = None,
    message: str | None = None,
    status: int | None = None,
    error: BaseException | None = None,
    log_path: str = _DEFAULT_LOG_PATH,
) -> None:
    """Write one JSON record describing a Dinler fallback attempt.

    ``outcome`` is one of: ``resolved``, ``miss``, ``transport_error``,
    ``parse_error``, ``http_error``. Keep the taxonomy small — the
    summary bucket count is only useful when outcomes stay stable.
    """
    rec: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sku": str(sku),
        "sku_dotted": format_sku_with_dots(sku),
        "outcome": outcome,
    }
    if state is not None:
        rec["state"] = state
    if stock_amount is not None:
        rec["stock_amount"] = stock_amount
    if message is not None:
        rec["message"] = str(message)[:240]
    if status is not None:
        rec["status"] = int(status)
    if error is not None:
        rec["error_class"] = type(error).__name__
        rec["error_signature"] = _normalize_error_signature(error)
    elif message and outcome in ("miss", "http_error"):
        rec["error_signature"] = _normalize_error_signature(message)

    line = json.dumps(rec, ensure_ascii=False)
    try:
        _get_logger(log_path).info(line)
    except Exception:
        # Logging must never kill a scrape.
        pass


def iter_records(log_path: str = _DEFAULT_LOG_PATH) -> Iterable[dict]:
    """Yield each JSON record from the log; silently skips malformed lines."""
    if not os.path.isfile(log_path):
        return
    with open(log_path, "r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue


def summarize_log(log_path: str = _DEFAULT_LOG_PATH, top_n: int = 10) -> dict:
    """Collapse the JSONL log into counts the reporter can email/print.

    Returns a dict with:
      - ``total_attempts``: every line in the log
      - ``unique_skus``: how many distinct products hit the fallback
      - ``by_outcome``: Counter-style dict keyed by outcome tag
      - ``top_error_signatures``: list of ``(signature, count)`` pairs
      - ``log_path``: echoed back so the caller can cite the source
    """
    outcomes: Counter[str] = Counter()
    error_sigs: Counter[str] = Counter()
    unique_skus: set[str] = set()
    total = 0
    for rec in iter_records(log_path):
        total += 1
        outcomes[rec.get("outcome", "unknown")] += 1
        sku = rec.get("sku_dotted") or rec.get("sku")
        if sku:
            unique_skus.add(str(sku))
        sig = rec.get("error_signature")
        if sig:
            error_sigs[sig] += 1
    return {
        "log_path": log_path,
        "total_attempts": total,
        "unique_skus": len(unique_skus),
        "by_outcome": dict(outcomes),
        "top_error_signatures": error_sigs.most_common(top_n),
    }


def format_summary(summary: dict) -> str:
    """Render the summary dict as a human-readable report block."""
    lines = [
        "─── Dinler fallback summary ─────────────────────────────",
        f"log file         : {summary.get('log_path')}",
        f"fallback attempts: {summary.get('total_attempts', 0)}",
        f"unique products  : {summary.get('unique_skus', 0)}",
        "by outcome:",
    ]
    by_outcome = summary.get("by_outcome") or {}
    if by_outcome:
        for outcome, count in sorted(by_outcome.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {outcome:<16s} {count}")
    else:
        lines.append("  (no attempts recorded)")
    top = summary.get("top_error_signatures") or []
    if top:
        lines.append("top error signatures:")
        for sig, count in top:
            lines.append(f"  [{count:>4d}] {sig}")
    lines.append("─────────────────────────────────────────────────────────")
    return "\n".join(lines)
