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
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis
from bs4 import BeautifulSoup
from dotenv import load_dotenv

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

MASTER_URL_RE = re.compile(r"ViewProduct-Start\?SKU=(P-\d+)")
ARTICLE_TABLE_RE = re.compile(r"ViewProduct-GetArticleTable\?[^\"']+")
API_SKU_RE = re.compile(r"SKU=(\d+)")

DEFAULT_STATUS_UNKNOWN = "Stok bilgisi bulunamadi"
MAX_ATTEMPTS = 3


def requeue_or_drop(redis_client, queue_key: str, payload: dict, logger, label: str) -> None:
    """Re-push `payload` onto `queue_key` with an incremented attempt count,
    or give up (log + drop) once MAX_ATTEMPTS is exceeded."""
    attempt = payload.get("attempt", 0) + 1
    if attempt > MAX_ATTEMPTS:
        logger.error(f"{label}: giving up after {MAX_ATTEMPTS} attempts")
        return
    redis_client.lpush(queue_key, json.dumps({**payload, "attempt": attempt}))
    logger.warning(f"{label}: re-queued (attempt {attempt}/{MAX_ATTEMPTS})")


def get_redis():
    return redis.from_url(REDIS_URL, decode_responses=True)


def is_master_url(url: str) -> bool:
    return "ViewProduct-Start" in url and "SKU=P-" in url


def is_article_table_url(url: str) -> bool:
    return "ViewProduct-GetArticleTable" in url


def is_api_url(url: str) -> bool:
    return "ViewProduct-GetPriceAndAvailabilityInformationPDS" in url


def build_api_url(article_no: str) -> str:
    return (
        f"{HAFELE_API_BASE}?SKU={article_no}"
        f"&ProductQuantity=20000&SynchronizationAjaxToken=1"
    )


def extract_article_numbers(html: bytes) -> list:
    """Return all article numbers from div.row.list-view.article data-value."""
    soup = BeautifulSoup(html, "html.parser")
    numbers = []
    seen = set()
    for div in soup.find_all("div", class_="row"):
        classes = div.get("class", [])
        if "list-view" in classes and "article" in classes:
            dv = (div.get("data-value") or "").strip()
            if dv.isdigit() and dv not in seen:
                seen.add(dv)
                numbers.append(dv)
    return numbers


def extract_master_metadata(html: bytes) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    name = None
    h1 = soup.find("h1", class_="productHeadline")
    if h1:
        name = h1.get_text(strip=True) or None
    if not name:
        title = soup.find("title")
        if title:
            name = title.get_text(strip=True).split(" - ")[0] or None

    subline = None
    sub_el = soup.select_one("h2.productSubline, .article-number")
    if sub_el:
        raw = sub_el.get_text(" ", strip=True)
        subline = re.sub(r"\s*Ürün kopyalandı\.?\s*", "", raw).strip() or None

    meta_desc = None
    md = soup.find("meta", {"name": "description"})
    if md:
        meta_desc = (md.get("content") or "").strip() or None

    return {"name": name, "subline": subline, "meta_description": meta_desc}


def extract_article_table_url(html: bytes) -> str | None:
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


def parse_price_from_html(soup: BeautifulSoup) -> dict:
    """Extract price strings from the visible spans in the API HTML.

    Order (matches legacy): [net, sales, suggested_retail].
    """
    spans = soup.select("span.price")
    values = [_clean_price(s.get_text(strip=True)) for s in spans]
    return {
        "kdv_haric_net_fiyat": values[0] if len(values) > 0 else None,
        "kdv_haric_satis_fiyati": values[1] if len(values) > 1 else None,
        "kdv_haric_tavsiye_edilen_perakende_fiyat": values[2] if len(values) > 2 else None,
    }


def parse_stock_from_values_tr(soup: BeautifulSoup) -> tuple[str | None, int | None]:
    """Iterate tr.values-tr rows to find (stok_durumu, stock_amount).

    Priority (mirrors legacy handle_singular_product):
      - Prefer any row whose availability text contains 'stokta mevcut'
      - Otherwise use the first row that has both a qty AND an availability flag
      - Rows without a valid qty or without a flag are skipped
    """
    preferred = None
    fallback = None
    for row in soup.select("tr.values-tr"):
        qty_el = row.select_one("td.qty-available")
        avail_el = row.select_one("td.requestedPackageStatus .availability-flag")
        if not qty_el or not avail_el:
            continue
        qty_text = qty_el.get_text(strip=True)
        avail_text = avail_el.get_text(strip=True)
        if not avail_text:
            continue
        qty = int(qty_text) if qty_text.isdigit() else None
        if "stokta mevcut" in avail_text.lower():
            preferred = ("stokta mevcut", qty)
            break
        if fallback is None:
            fallback = (avail_text, qty)
    return preferred or fallback or (None, None)


def parse_stock_fallback(soup: BeautifulSoup) -> str | None:
    """Fallback: use #productAvailabilityInformation .availability-flag text."""
    el = soup.select_one("#productAvailabilityInformation .availability-flag")
    if el:
        txt = el.get_text(strip=True)
        return txt or None
    return None

