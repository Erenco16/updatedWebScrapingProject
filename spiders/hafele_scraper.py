"""
spiders/hafele_scraper.py  ── SCRAPER (Scrapy-Redis Spider)

Pops variant price/stock API URLs from hafele:scrape_queue (pushed by the
separate discovery spider, spiders/hafele_discovery.py), fetches real
price/stock data, and yields the item for spiders.pipelines.SQLitePipeline
to hand off to db_writer.py. Runs as its own set of containers,
concurrently with the discovery pool.
"""
import json

from bs4 import BeautifulSoup
from scrapy import Request
from scrapy_redis.spiders import RedisSpider

from spiders.headers import API_HEADERS
from spiders.hafele_parsing import (
    SCRAPE_QUEUE_KEY,
    REDIS_META_HASH,
    REDIS_URL,
    REDIS_COOKIES_KEY,
    API_SKU_RE,
    DEFAULT_STATUS_UNKNOWN,
    parse_price_from_html,
    parse_stock_from_values_tr,
    parse_stock_fallback,
    get_redis,
    requeue_or_drop,
)


class HafeleScraperSpider(RedisSpider):
    name = "hafele_scraper"
    redis_key = SCRAPE_QUEUE_KEY

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
        raw = data.decode("utf-8") if isinstance(data, bytes) else data
        payload = json.loads(raw)
        return Request(
            url=payload["url"],
            callback=self.parse_product_api,
            errback=self.on_failure,
            meta={"payload": payload},
            dont_filter=True,
            headers=API_HEADERS,
        )

    def parse_product_api(self, response):
        payload = response.meta["payload"]
        api_url = payload["url"]
        sku_m = API_SKU_RE.search(api_url)
        sku = sku_m.group(1) if sku_m else ""

        if response.status != 200:
            self.logger.warning(f"API SKU={sku} status {response.status}")
            requeue_or_drop(get_redis(), SCRAPE_QUEUE_KEY, payload, self.logger, f"API SKU={sku}")
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

    def on_failure(self, failure):
        payload = failure.request.meta["payload"]
        sku_m = API_SKU_RE.search(payload["url"])
        sku = sku_m.group(1) if sku_m else "?"
        self.logger.warning(f"API SKU={sku} request failed: {failure.value}")
        requeue_or_drop(
            get_redis(), SCRAPE_QUEUE_KEY, payload, self.logger,
            f"API SKU={sku} (network error)",
        )
