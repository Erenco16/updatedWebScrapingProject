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
# "Hafele parsed as unknown-status" retries. Three immediate head-of-queue
# retries with exponential backoff (1s, 2s, 4s) run on the FIRST pass. If
# all three retries still can't resolve stock info, the SKU is deferred to
# the END of the queue with ``second_pass=True`` and gets one more Hafele
# attempt after everything else drains. Only if THAT also fails do we fall
# back to Dinler — Dinler is now explicitly last-resort instead of fired
# on the first unknown parse.
MAX_UNKNOWN_RETRIES = 3

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


def _parse_hafele_qty(qty_text: str) -> int | None:
    """Turn Hafele's rendered stock-count string into an int.

    Hafele uses the Turkish numeric locale: dot is the *thousands*
    separator, not the decimal point. So "13.600" means 13 600 units,
    not 13.6. Trailing whitespace / \\n chars survive Scrapling's
    text extraction, so we strip aggressively before trying ``int()``.
    """
    if not qty_text:
        return None
    cleaned = (
        qty_text.strip()
        .replace("\xa0", "")      # NBSP sometimes separates thousands
        .replace(" ", "")
        .replace(".", "")         # thousands separator
        .replace("\n", "")
        .replace("\r", "")
        .replace("\t", "")
    )
    return int(cleaned) if cleaned.isdigit() else None


# Scrapling's adaptive selector can misfire two ways on Hafele's stock
# tables; both have produced bad DB rows in prior runs:
#
# 1. The response has an *order-qty* subtype row (``tr.values-tr.order-qty``,
#    a "minimum order quantity" / packaging-size row, NOT inventory):
#       <tr class="values-tr order-qty">
#         <td class=" qty-available">Ambalaj birimi 1</td>  <-- a label
#         <td class="availablePackageStatus">                <-- different class
#           <span class="availability-flag">stokta mevcut</span>
#         </td>
#       </tr>
#    Adaptive match treats ``availablePackageStatus`` as a close enough
#    neighbour of our target ``requestedPackageStatus``, so we read
#    ``"stokta mevcut"`` from that row and then try to parse qty text
#    like ``"Ambalaj birimi 1"`` -> int which gives None. Result:
#    ``("stokta mevcut", None)`` instead of the real inventory row's
#    status, or worse, a false-positive "in stock" when the item is on
#    request/backorder.
#
# 2. ``parse_stock_fallback``'s ``#productAvailabilityInformation
#    .availability-flag`` selector hits an empty span. Adaptive match
#    then relocates to the nearest similar ``<span>``, which turns out
#    to be the ``<span class="perUnit"># Adet (ADT)</span>`` in the
#    price block. That's how ``# Adet (ST)`` / ``# Set (GR)`` /
#    ``# Çift (Çift)`` wound up as ``stok_durumu`` for 3,855 rows.
#
# Defense in depth: (a) explicitly skip ``order-qty`` rows,
# (b) reject any avail text that looks like a unit-label pollutant,
# (c) reject qty text that looks like a packaging label.

_ORDER_QTY_ROW_RE = re.compile(r"\border-qty\b")
_UNIT_LABEL_RE = re.compile(r"^\s*#|ambalaj birimi", re.IGNORECASE)


def _looks_like_unit_label(text: str) -> bool:
    """True if ``text`` looks like a packaging/unit label (``# Adet (ST)``,
    ``Ambalaj birimi 1``, etc.) rather than a real availability flag or qty.
    """
    if not text:
        return False
    return bool(_UNIT_LABEL_RE.search(text))


def _is_order_qty_row(row) -> bool:
    """True if the given Scrapling row is a Type B ``order-qty`` row
    (minimum-order / packaging-size, not inventory)."""
    try:
        classes = row.attrib.get("class") or ""
    except Exception:
        return False
    return bool(_ORDER_QTY_ROW_RE.search(classes))


def parse_stock_from_values_tr(html: bytes) -> tuple[str | None, int | None]:
    """Iterate tr.values-tr rows to find (stok_durumu, stock_amount).

    Priority (mirrors legacy handle_singular_product):
      - Prefer any row whose availability text contains 'stokta mevcut'
        AND has a parseable numeric qty. A row that says "stokta mevcut"
        but reports an unparseable qty (eg a packaging label that
        Scrapling's adaptive match stole into the qty column) must NOT
        win over a later "stokta mevcut" row that has real inventory.
      - Fall back to the first row that has both a qty and an
        availability flag.
      - Rows without an availability flag are skipped entirely.
      - ``order-qty`` subtype rows (minimum-order-qty / packaging-size,
        not inventory) are skipped entirely to defeat Scrapling's
        adaptive drift onto ``availablePackageStatus``.

    The top-level ``tr.values-tr`` lookup is strict (adaptive=False).
    Previously adaptive drift would relocate to BOM-product
    ``<tr>`` wrappers that live outside the normal variant table and
    produced false ``("stokta mevcut", None)`` returns for 94 Bill-of-
    Materials SKUs. BOM products have their own dedicated parser —
    ``parse_stock_from_bom`` below.
    """
    page = _selector(html)
    preferred = None       # ("stokta mevcut", qty>=0) — hard match
    preferred_noqty = None # ("stokta mevcut", None)   — soft match
    fallback = None        # first (any_status, qty) we can read
    rows = page.css("tr.values-tr", auto_save=True, adaptive=False) or []
    for row in rows:
        if _is_order_qty_row(row):
            continue  # Type B; not real inventory
        qty_text = _safe_text(_css_first(row, "td.qty-available", **_ADAPTIVE_KW))
        avail_text = _safe_text(
            _css_first(row, "td.requestedPackageStatus .availability-flag", **_ADAPTIVE_KW)
        )
        # Guard against adaptive-match pollution: reject any text that
        # looks like a packaging label (#-prefixed unit, "Ambalaj
        # birimi …", etc.).
        if _looks_like_unit_label(avail_text):
            avail_text = ""
        if _looks_like_unit_label(qty_text):
            qty_text = ""
        if not avail_text:
            continue
        qty = _parse_hafele_qty(qty_text)
        if "stokta mevcut" in avail_text.lower():
            if qty is not None:
                preferred = ("stokta mevcut", qty)
                break  # best possible match found; stop scanning
            if preferred_noqty is None:
                preferred_noqty = ("stokta mevcut", None)
            continue
        if fallback is None:
            fallback = (avail_text, qty)
    return preferred or preferred_noqty or fallback or (None, None)


# BOM / Kit products expose per-component availability in a totally
# different DOM shape — no ``tr.values-tr`` table. Each component gets
# one ``<div class="bomArticleStatus"><span class="availability-flag">
# stokta mevcut</span></div>`` plus a sibling cell
# ``<td class="bomArticleStatus"> 20000 Adet (ADT) </td>`` carrying the
# quantity. The qty text leads with a Turkish-locale integer and then a
# unit suffix (``Adet``, ``Çift``, ``Set``, ``Metre``, ``Kilogram``, …).
_BOM_QTY_RE = re.compile(r"^\s*([\d.,\s ]+?)\s+\S")


def _parse_bom_qty(td_text: str) -> int | None:
    """Pull the leading integer out of a ``bomArticleStatus`` cell."""
    if not td_text:
        return None
    m = _BOM_QTY_RE.match(td_text.strip())
    if not m:
        return None
    return _parse_hafele_qty(m.group(1))


def parse_stock_from_bom(html: bytes) -> tuple[str | None, int | None]:
    """Parse Hafele's BOM / Kit product shape.

    Looks for pairs of ``div.bomArticleStatus`` (holds the availability
    flag) and ``td.bomArticleStatus`` (holds the quantity + unit
    label). Returns the "best" pair using the same priority as
    ``parse_stock_from_values_tr``:

      1. First ``stokta mevcut`` component with a parseable qty wins.
      2. Else first ``stokta mevcut`` component (qty None) wins.
      3. Else first component with any status (qty optional) wins.
      4. Else ``(None, None)`` so the Dinler fallback can take over.
    """
    page = _selector(html)
    status_divs = page.css("div.bomArticleStatus", auto_save=True, adaptive=False) or []
    qty_tds = page.css("td.bomArticleStatus", auto_save=True, adaptive=False) or []
    if not status_divs:
        return (None, None)

    preferred = None
    preferred_noqty = None
    fallback = None

    for i, div in enumerate(status_divs):
        flag = _safe_text(_css_first(div, "span.availability-flag", auto_save=True, adaptive=False))
        if _looks_like_unit_label(flag):
            flag = ""
        if not flag:
            continue
        qty_td = qty_tds[i] if i < len(qty_tds) else None
        qty_text = _safe_text(qty_td) if qty_td is not None else ""
        qty = _parse_bom_qty(qty_text) if qty_text else None

        if "stokta mevcut" in flag.lower():
            if qty is not None:
                preferred = ("stokta mevcut", qty)
                break
            if preferred_noqty is None:
                preferred_noqty = ("stokta mevcut", None)
            continue
        if fallback is None:
            fallback = (flag, qty)

    return preferred or preferred_noqty or fallback or (None, None)


def parse_stock_fallback(html: bytes) -> str | None:
    """Fallback: use #productAvailabilityInformation .availability-flag text.

    Must NOT use adaptive matching here. When the real
    ``.availability-flag`` span is empty, Scrapling's adaptive fallback
    relocates to the nearest similar ``<span>`` and the nearest one in a
    Hafele PDS response is ``<span class="perUnit"># Adet (ADT)</span>``
    inside the price block. That misfire was the source of 3,855 bad
    ``stok_durumu`` values (``# Adet (ST)`` / ``# Set (GR)`` /
    ``# Çift (Çift)`` / etc.) in the previous full run.
    """
    page = _selector(html)
    # Direct raw match only; no adaptive relocation. If this returns
    # nothing, we'd rather fall through to the Dinler API than invent a
    # fake status from a cross-element span.
    node = _css_first(
        page, "#productAvailabilityInformation .availability-flag",
        auto_save=True, adaptive=False,
    )
    txt = _safe_text(node)
    if _looks_like_unit_label(txt):
        return None
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
