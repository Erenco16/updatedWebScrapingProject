"""
spiders/hafele_processor.py  ── CONSUMER (Scrapy-Redis Spider)

Two-stage pipeline with authenticated cookies:
  Stage 1: Pop MASTER URL (ViewProduct-Start?SKU=P-XXXXXX) -> fetch HTML
           -> extract div.row.list-view.article data-value -> queue API URLs
  Stage 2: Pop API URL (ViewProduct-GetPriceAndAvailabilityInformationPDS?SKU=...)
           -> parse tr.values-tr rows for real stock status -> save to SQLite
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from scrapy import Request
from scrapy_redis.spiders import RedisSpider

from spiders.headers import API_HEADERS, BROWSER_HEADERS

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://hafele-redis:6379")
REDIS_QUEUE_KEY = "hafele:api_urls"
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


class HafeleProcessor(RedisSpider):
    name = "hafele_processor"
    redis_key = REDIS_QUEUE_KEY

    # Auth backend is slow — 10 procs × high concurrency triggered Cloudflare 524s.
    # Keep 10 replicas (for master crawl parallelism) but throttle per-processor.
    # RedisCookieMiddleware auto-injects fresh session cookies (60s cache) —
    # no per-request cookies= needed here, and no restart needed when the
    # cookie-refresher sidecar updates them.
    custom_settings = {
        "CONCURRENT_REQUESTS": 3,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 3,
        "DOWNLOAD_DELAY": 1.0,
        "RANDOMIZE_DOWNLOAD_DELAY": 0.5,
        "RETRY_TIMES": 5,
        "RETRY_HTTP_CODES": [403, 408, 429, 500, 502, 503, 504, 520, 521, 522, 524],
        "DOWNLOAD_TIMEOUT": 60,
        "ITEM_PIPELINES": {"spiders.pipelines.SQLitePipeline": 300},
        "REDIS_URL": REDIS_URL,
        "LOG_LEVEL": "INFO",
        "SCHEDULER_IDLE_BEFORE_CLOSE": 30,
        "CLOSESPIDER_TIMEOUT": 3600,
        "COOKIE_CACHE_TTL": 60,
        "COOKIE_REDIS_KEY": REDIS_COOKIES_KEY,
        "DOWNLOADER_MIDDLEWARES": {
            "scrapy.downloadermiddlewares.retry.RetryMiddleware": 90,
            "spiders.middlewares.RedisCookieMiddleware": 100,
        },
    }

    def make_request_from_data(self, data):
        url = data.decode("utf-8") if isinstance(data, bytes) else data
        url = url.strip()

        if is_master_url(url):
            return Request(
                url=url,
                callback=self.parse_master,
                meta={"master_url": url},
                dont_filter=True,
                headers=BROWSER_HEADERS,
            )
        if is_article_table_url(url):
            return Request(
                url=url,
                callback=self.parse_article_table,
                meta={"article_table_url": url},
                dont_filter=True,
                headers=API_HEADERS,
            )
        if is_api_url(url):
            return Request(
                url=url,
                callback=self.parse_product_api,
                meta={"api_url": url},
                dont_filter=True,
                headers=API_HEADERS,
            )

        self.logger.warning(f"Unknown URL, defaulting to API parse: {url[:80]}")
        return Request(
            url=url,
            callback=self.parse_product_api,
            meta={"api_url": url},
            dont_filter=True,
            headers=API_HEADERS,
        )

    def parse_master(self, response):
        master_url = response.meta.get("master_url", response.url)
        master_sku_m = MASTER_URL_RE.search(master_url)
        master_sku = master_sku_m.group(1) if master_sku_m else "?"

        if response.status != 200:
            self.logger.warning(f"Master {master_sku} returned status {response.status}")
            return

        meta = extract_master_metadata(response.body)
        redis_client = get_redis()
        if meta.get("name") or meta.get("meta_description"):
            redis_client.hset(REDIS_META_HASH, master_sku, json.dumps(meta))

        article_nos = extract_article_numbers(response.body)
        self.logger.info(
            f"Master {master_sku}: found {len(article_nos)} article(s) on landing page"
        )

        for art in article_nos:
            api_url = build_api_url(art)
            redis_client.lpush(REDIS_QUEUE_KEY, api_url)
            redis_client.hset(
                REDIS_META_HASH, art, json.dumps({**meta, "master_sku": master_sku})
            )

        if not article_nos:
            table_url = extract_article_table_url(response.body)
            if table_url:
                self.logger.info(f"Master {master_sku}: following ArticleTable {table_url[:100]}")
                yield Request(
                    url=table_url,
                    callback=self.parse_article_table,
                    meta={"article_table_url": table_url, "master_sku": master_sku},
                    dont_filter=True,
                    headers=API_HEADERS,
                )

    def parse_article_table(self, response):
        master_sku = response.meta.get("master_sku", "?")
        if response.status != 200:
            self.logger.warning(
                f"ArticleTable for {master_sku} returned status {response.status}"
            )
            return

        redis_client = get_redis()
        meta_json = redis_client.hget(REDIS_META_HASH, master_sku) or "{}"
        meta = json.loads(meta_json)

        article_nos = extract_article_numbers(response.body)
        self.logger.info(
            f"ArticleTable {master_sku}: found {len(article_nos)} article(s)"
        )
        for art in article_nos:
            api_url = build_api_url(art)
            redis_client.lpush(REDIS_QUEUE_KEY, api_url)
            redis_client.hset(
                REDIS_META_HASH, art, json.dumps({**meta, "master_sku": master_sku})
            )

    def parse_product_api(self, response):
        api_url = response.meta.get("api_url", response.url)
        sku_m = API_SKU_RE.search(api_url)
        sku = sku_m.group(1) if sku_m else ""

        if response.status != 200:
            self.logger.warning(f"API SKU={sku} status {response.status}")
            return

        soup = BeautifulSoup(response.body, "html.parser")

        # Real stock status from tr.values-tr rows (legacy logic)
        stok_durumu, stock_amount = parse_stock_from_values_tr(soup)

        # Fallback: whole-product availability info bar
        if not stok_durumu:
            stok_durumu = parse_stock_fallback(soup) or DEFAULT_STATUS_UNKNOWN

        # Prices
        price_info = parse_price_from_html(soup)

        # Enrich description
        redis_client = get_redis()
        meta_json = redis_client.hget(REDIS_META_HASH, sku)
        meta = json.loads(meta_json) if meta_json else {}
        description = meta.get("name") or meta.get("meta_description") or ""
        if meta.get("subline"):
            description = f"{description} | {meta['subline']}".strip(" |")

        item = {
            "sku": sku,
            "stock_code": sku,
            "kdv_haric_net_fiyat": price_info.get("kdv_haric_net_fiyat"),
            "kdv_haric_tavsiye_edilen_perakende_fiyat": price_info.get(
                "kdv_haric_tavsiye_edilen_perakende_fiyat"
            ),
            "kdv_haric_satis_fiyati": price_info.get("kdv_haric_satis_fiyati"),
            "stok_durumu": stok_durumu,
            "stock_amount": stock_amount,
            "product_description": description or "",
            "is_group_product": 0,
        }
        self.logger.info(
            f"API SKU={sku} status='{stok_durumu}' qty={stock_amount}"
        )
        yield item
