"""
spiders/hafele_parsing.py  ── shared parsing/queue helpers

Used by both spiders/hafele_discovery.py and spiders/hafele_scraper.py,
which run as separate services/containers so discovery (master URL ->
variant SKUs) and scraping (variant SKU -> price/stock) proceed
concurrently instead of interleaved in one processor pool:

  Discovery: pop MASTER URL (ViewProduct-Start?SKU=P-XXXXXX) -> fetch HTML
             -> extract div.row.list-view.article data-value -> push each
             variant's API URL onto SCRAPE_QUEUE_KEY.
  Scraper:   pop API URL (ViewProduct-GetPriceAndAvailabilityInformationPDS
             ?SKU=...) -> parse tr.values-tr rows for real stock status ->
             save to SQLite (via db_writer.py).

A URL is removed from its queue the moment it's popped (that's how the
underlying scrapy-redis polling works), so "retry on failure" here means:
on a permanent failure (Scrapy's own RETRY_TIMES exhausted, or a
downloader-level error), re-push a fresh entry onto the same queue with
an incremented attempt count, up to MAX_ATTEMPTS, instead of the old
behaviour of silently dropping it.

HTML parsing uses Scrapling's Adaptor, not BeautifulSoup. Adaptor is a
drop-in replacement with CSS/XPath selectors plus adaptive selector
tracking (``auto_save=True`` fingerprints each match, ``adaptive=True``
re-finds elements by fingerprint when the raw selector drifts due to a
layout redesign). Fingerprints live on the mounted data volume so they
survive container restarts.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis
from dotenv import load_dotenv

# Scrapling renamed the parsing entry point ``Adaptor`` -> ``Selector`` in
# 0.4; both expose the same CSS/XPath + adaptive-selector surface.
from scrapling import Selector

from spiders.models import format_sku_with_dots

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://hafele-redis:6379")
MASTER_QUEUE_KEY = "hafele:master_urls"
SCRAPE_QUEUE_KEY = "hafele:scrape_queue"
REDIS_META_HASH = "hafele:master:meta"
REDIS_COOKIES_KEY = "hafele:session:cookies"

HAFELE_BASE = "https://www.hafele.com.tr"
HAFELE_API_BASE = (
    f"{HAFELE_BASE}/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/"
    "ViewProduct-GetPriceAndAvailabilityInformationPDS"
)

# Dinler Mobilya's public stock API. Used as a fallback whenever Hafele's
# own availability endpoint returns no stock row for a given variant
# (stok_durumu == DEFAULT_STATUS_UNKNOWN). Takes the dotted SKU form
# (e.g. 901.98.256), not the digits-only form Hafele's API uses.
DINLER_STOCK_URL = "https://www.dinlermobilya.com.tr/api/stock"


import re  # noqa: E402  (kept after dotenv import for readability)

MASTER_URL_RE = re.compile(r"ViewProduct-Start\?SKU=(P-\d+)")
ARTICLE_TABLE_RE = re.compile(r"ViewProduct-GetArticleTable\?[^\"']+")
API_SKU_RE = re.compile(r"SKU=(\d+)")

DEFAULT_STATUS_UNKNOWN = "Stok bilgisi bulunamadi"
MAX_ATTEMPTS = 3
# Network errors get their own generous cap so a transient outage (docker
# network flapping, brief DNS blip, upstream restart) doesn't burn through
# the 3-attempt application budget in seconds.
MAX_NET_ATTEMPTS = 15

# Where Scrapling persists its adaptive-selector fingerprints. Must sit
# on the mounted ./data volume so the fingerprints survive container
# recreation; otherwise auto_match degrades back to raw-selector matching
# after every rebuild.
_SCRAPLING_STORAGE_DIR = os.getenv("SCRAPLING_STORAGE_DIR", "/app/data")
try:
    os.makedirs(_SCRAPLING_STORAGE_DIR, exist_ok=True)
except OSError:
    pass
SCRAPLING_STORAGE_FILE = os.path.join(_SCRAPLING_STORAGE_DIR, "scrapling_tracker.db")

# Pass to every `.css()` call: save a fingerprint whenever a selector
# matches so we keep learning the real DOM shape, and transparently
# fall back to adaptive match when the raw selector no longer resolves.
# Keep as module-level constant so a Scrapling kwarg change only needs
# one edit site.
_ADAPTIVE_KW = dict(auto_save=True, adaptive=True)


def _selector(html: bytes | str, url: str | None = None) -> Selector:
    """Build a Scrapling Selector with adaptive-selector tracking enabled.

    Centralised so every parser in this file shares the same storage
    file configuration — otherwise fingerprints would be scattered
    across tempfiles and defeat the whole point.

    ``adaptive=True`` on the Selector enables Scrapling's whole-document
    fingerprint tracker; per-call ``auto_save`` / ``adaptive`` kwargs on
    ``.css()`` then save the fingerprint on match and fall back to
    adaptive match when the raw selector no longer resolves.
    """
    content = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    try:
        return Selector(
            content=content,
            url=url or HAFELE_BASE,
            adaptive=True,
            storage_args={"storage_file": SCRAPLING_STORAGE_FILE},
        )
    except (TypeError, ValueError):
        # Guard against Scrapling kwarg renames between versions.
        return Selector(content=content, url=url or HAFELE_BASE, adaptive=True)


def _css_first(root, selector: str, **kwargs):
    """Scrapling 0.4 dropped ``.css_first()``; this is the equivalent
    ``.css(..)[0] or None`` the whole parser can share."""
    if root is None:
        return None
    try:
        nodes = root.css(selector, **kwargs)
    except Exception:
        return None
    if not nodes:
        return None
    try:
        return nodes[0]
    except (IndexError, TypeError):
        return None


def requeue_or_drop(
    redis_client,
    queue_key: str,
    payload: dict,
    logger,
    label: str,
    count_attempt: bool = True,
) -> None:
    """Re-push `payload` onto `queue_key`.

    - `count_attempt=True` (application error, e.g. 403/5xx after retries,
      "no article numbers found"): bump `attempt`, drop after MAX_ATTEMPTS.
    - `count_attempt=False` (transport/network error before we ever got a
      Response): bump `net_attempt` instead, drop only after
      MAX_NET_ATTEMPTS so a bad network window doesn't silently trash the
      queue.
    """
    if count_attempt:
        attempt = payload.get("attempt", 0) + 1
        if attempt > MAX_ATTEMPTS:
            logger.error(f"{label}: giving up after {MAX_ATTEMPTS} attempts")
            return
        redis_client.lpush(queue_key, json.dumps({**payload, "attempt": attempt}))
        logger.warning(f"{label}: re-queued (attempt {attempt}/{MAX_ATTEMPTS})")
    else:
        net_attempt = payload.get("net_attempt", 0) + 1
        if net_attempt > MAX_NET_ATTEMPTS:
            logger.error(f"{label}: giving up after {MAX_NET_ATTEMPTS} network attempts")
            return
        redis_client.lpush(queue_key, json.dumps({**payload, "net_attempt": net_attempt}))
        logger.warning(
            f"{label}: re-queued (net_attempt {net_attempt}/{MAX_NET_ATTEMPTS}, network error)"
        )


def get_redis():
    return redis.from_url(REDIS_URL, decode_responses=True)


def is_master_url(url: str) -> bool:
    return "ViewProduct-Start" in url and "SKU=P-" in url


def is_article_table_url(url: str) -> bool:
    return "ViewProduct-GetArticleTable" in url


def is_api_url(url: str) -> bool:
    return "ViewProduct-GetPriceAndAvailabilityInformationPDS" in url


def is_dinler_url(url: str) -> bool:
    return url.startswith(DINLER_STOCK_URL)


def build_api_url(article_no: str) -> str:
    return (
        f"{HAFELE_API_BASE}?SKU={article_no}"
        f"&ProductQuantity=20000&SynchronizationAjaxToken=1"
    )


def build_dinler_url(article_no: str) -> str:
    """Dinler expects the dotted SKU format (901.98.256), not the
    digits-only form Hafele's internal API uses."""
    return f"{DINLER_STOCK_URL}?sku={format_sku_with_dots(article_no)}&quantity=1"


def _safe_text(node) -> str:
    """Scrapling nodes expose ``.text`` as a property that can be ``None``
    on empty tags; this normalises to a stripped string so callers never
    need to guard against ``NoneType.strip``."""
    if node is None:
        return ""
    try:
        txt = node.text
    except Exception:
        return ""
    if txt is None:
        return ""
    try:
        return txt.clean() if hasattr(txt, "clean") else str(txt).strip()
    except Exception:
        return str(txt).strip() if txt else ""


def extract_article_numbers(html: bytes) -> list:
    """Return all article numbers from div.row.list-view.article data-value.

    Uses Scrapling's adaptive selectors so a layout rename (e.g. the row
    class changing from ``list-view`` to ``variant-row``) is handled
    transparently once the fingerprint for that element has been saved.
    """
    page = _selector(html)
    numbers: list[str] = []
    seen: set[str] = set()
    nodes = page.css("div.row.list-view.article", **_ADAPTIVE_KW) or []
    for div in nodes:
        dv = (div.attrib.get("data-value") or "").strip() if div else ""
        if dv.isdigit() and dv not in seen:
            seen.add(dv)
            numbers.append(dv)
    return numbers


def extract_master_metadata(html: bytes) -> dict:
    page = _selector(html)

    name = _safe_text(_css_first(page, "h1.productHeadline", **_ADAPTIVE_KW)) or None
    if not name:
        title_text = _safe_text(_css_first(page, "title", **_ADAPTIVE_KW))
        if title_text:
            name = title_text.split(" - ")[0] or None

    subline_raw = (
        _safe_text(_css_first(page, "h2.productSubline", **_ADAPTIVE_KW))
        or _safe_text(_css_first(page, ".article-number", **_ADAPTIVE_KW))
    )
    if subline_raw:
        subline = re.sub(r"\s*Ürün kopyalandı\.?\s*", "", subline_raw).strip() or None
    else:
        subline = None

    meta_desc_node = _css_first(page, "meta[name='description']", **_ADAPTIVE_KW)
    meta_desc = None
    if meta_desc_node is not None:
        content = (meta_desc_node.attrib.get("content") or "").strip()
        meta_desc = content or None

    return {"name": name, "subline": subline, "meta_description": meta_desc}


def extract_article_table_url(html: bytes) -> str | None:
    # Regex over the raw HTML is still the right call here: the URL lives
    # inside inline JS/attributes, not inside a DOM text node, so CSS/XPath
    # selectors would be the wrong shape. Keeping this as a plain regex
    # scan.
    m = ARTICLE_TABLE_RE.search(html.decode("utf-8", errors="replace"))
    if not m:
        return None
    url = m.group(0).replace("&amp;", "&")
    if url.startswith("http"):
        return url
    return f"{HAFELE_BASE}/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/{url}"


def _clean_price(txt: str | None) -> str | None:
    if not txt:
        return None
    txt = txt.strip()
    if not txt or txt.upper() == "N/A":
        return None
    return txt


def parse_price_from_html(html: bytes) -> dict:
    """Extract price strings from the visible spans in the API HTML.

    Order (matches legacy): [net, sales, suggested_retail].
    """
    page = _selector(html)
    spans = page.css("span.price", **_ADAPTIVE_KW) or []
    values = [_clean_price(_safe_text(s)) for s in spans]
    return {
        "kdv_haric_net_fiyat": values[0] if len(values) > 0 else None,
        "kdv_haric_satis_fiyati": values[1] if len(values) > 1 else None,
        "kdv_haric_tavsiye_edilen_perakende_fiyat": values[2] if len(values) > 2 else None,
    }


def parse_stock_from_values_tr(html: bytes) -> tuple[str | None, int | None]:
    """Iterate tr.values-tr rows to find (stok_durumu, stock_amount).

    Priority (mirrors legacy handle_singular_product):
      - Prefer any row whose availability text contains 'stokta mevcut'
      - Otherwise use the first row that has both a qty AND an availability flag
      - Rows without a valid qty or without a flag are skipped
    """
    page = _selector(html)
    preferred = None
    fallback = None
    rows = page.css("tr.values-tr", **_ADAPTIVE_KW) or []
    for row in rows:
        qty_text = _safe_text(_css_first(row, "td.qty-available", **_ADAPTIVE_KW))
        avail_text = _safe_text(
            _css_first(row, "td.requestedPackageStatus .availability-flag", **_ADAPTIVE_KW)
        )
        if not qty_text and not avail_text:
            continue
        if not avail_text:
            continue
        qty = int(qty_text) if qty_text.isdigit() else None
        if "stokta mevcut" in avail_text.lower():
            preferred = ("stokta mevcut", qty)
            break
        if fallback is None:
            fallback = (avail_text, qty)
    return preferred or fallback or (None, None)


def parse_stock_fallback(html: bytes) -> str | None:
    """Fallback: use #productAvailabilityInformation .availability-flag text."""
    page = _selector(html)
    node = _css_first(
        page, "#productAvailabilityInformation .availability-flag", **_ADAPTIVE_KW
    )
    txt = _safe_text(node)
    return txt or None


def normalize_stock_status(stok_durumu: str | None, stock_amount: int | None) -> str:
    """Collapse the free-form Turkish availability label into a bounded
    'In Stock' / 'Out of Stock' / 'Unknown' value for consumers that just
    want a boolean-ish view (e.g. BI tooling, filtering)."""
    if not stok_durumu or stok_durumu == DEFAULT_STATUS_UNKNOWN:
        return "Unknown"
    lowered = stok_durumu.lower()
    if "stokta mevcut" in lowered or "in_stock" in lowered or "in stock" in lowered:
        return "In Stock"
    if (
        "stokta yok" in lowered
        or "out_of_stock" in lowered
        or "out of stock" in lowered
    ):
        return "Out of Stock"
    if stock_amount is not None and stock_amount > 0:
        return "In Stock"
    if stock_amount == 0:
        return "Out of Stock"
    return stok_durumu  # keep the original label as-is when it carries info
