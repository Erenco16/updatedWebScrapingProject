"""
spiders/hafele_discovery.py  ── DISCOVERY (Scrapy-Redis Spider)

Pops MASTER URLs (ViewProduct-Start?SKU=P-XXXXXX) from
hafele:master_urls, discovers each master's variant SKUs, and pushes
their price-API URLs onto hafele:scrape_queue for the separate scraper
spider (spiders/hafele_scraper.py) to pick up. Runs as its own set of
containers, concurrently with the scraper pool -- not interleaved in one
processor as before.
"""
import json

from scrapy import Request
from scrapy_redis.spiders import RedisSpider

from spiders.headers import API_HEADERS, BROWSER_HEADERS
from spiders.hafele_parsing import (
    MASTER_QUEUE_KEY,
    SCRAPE_QUEUE_KEY,
    REDIS_META_HASH,
    REDIS_URL,
    REDIS_COOKIES_KEY,
    MASTER_URL_RE,
    is_article_table_url,
    extract_article_numbers,
    extract_master_metadata,
    extract_article_table_url,
    build_api_url,
    get_redis,
    requeue_or_drop,
)


class HafeleDiscoverySpider(RedisSpider):
    name = "hafele_discovery"
    redis_key = MASTER_QUEUE_KEY

    # Same throttle as the scraper: Hafele's authenticated backend is slow
    # regardless of which endpoint you hit, and higher concurrency here
    # previously triggered Cloudflare 524s.
    custom_settings = {
        "CONCURRENT_REQUESTS": 3,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 3,
        "DOWNLOAD_DELAY": 1.0,
        "RANDOMIZE_DOWNLOAD_DELAY": 0.5,
        "RETRY_TIMES": 5,
        "RETRY_HTTP_CODES": [403, 408, 429, 500, 502, 503, 504, 520, 521, 522, 524],
        "DOWNLOAD_TIMEOUT": 60,
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
        url = payload["url"]

        if is_article_table_url(url):
            return Request(
                url=url,
                callback=self.parse_article_table,
                errback=self.on_article_table_failure,
                meta={"payload": payload, "master_sku": payload.get("master_sku", "?")},
                dont_filter=True,
                headers=API_HEADERS,
            )
        return Request(
            url=url,
            callback=self.parse_master,
            errback=self.on_master_failure,
            meta={"payload": payload},
            dont_filter=True,
            headers=BROWSER_HEADERS,
        )

    def parse_master(self, response):
        payload = response.meta["payload"]
        master_url = payload["url"]
        master_sku_m = MASTER_URL_RE.search(master_url)
        master_sku = master_sku_m.group(1) if master_sku_m else "?"

        if response.status != 200:
            self.logger.warning(f"Master {master_sku} returned status {response.status}")
            requeue_or_drop(get_redis(), MASTER_QUEUE_KEY, payload, self.logger, f"Master {master_sku}")
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
            redis_client.lpush(SCRAPE_QUEUE_KEY, json.dumps({"url": api_url, "attempt": 0}))
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
                    errback=self.on_article_table_failure,
                    meta={
                        "payload": {"url": table_url, "attempt": 0, "master_sku": master_sku},
                        "master_sku": master_sku,
                    },
                    dont_filter=True,
                    headers=API_HEADERS,
                )

    def parse_article_table(self, response):
        payload = response.meta["payload"]
        master_sku = response.meta.get("master_sku", "?")
        if response.status != 200:
            self.logger.warning(
                f"ArticleTable for {master_sku} returned status {response.status}"
            )
            requeue_or_drop(get_redis(), MASTER_QUEUE_KEY, payload, self.logger, f"ArticleTable {master_sku}")
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
            redis_client.lpush(SCRAPE_QUEUE_KEY, json.dumps({"url": api_url, "attempt": 0}))
            redis_client.hset(
                REDIS_META_HASH, art, json.dumps({**meta, "master_sku": master_sku})
            )

    def on_master_failure(self, failure):
        payload = failure.request.meta["payload"]
        self.logger.warning(f"Master request failed: {failure.value}")
        requeue_or_drop(get_redis(), MASTER_QUEUE_KEY, payload, self.logger, "Master (network error)")

    def on_article_table_failure(self, failure):
        payload = failure.request.meta["payload"]
        master_sku = failure.request.meta.get("master_sku", "?")
        self.logger.warning(f"ArticleTable request failed for {master_sku}: {failure.value}")
        requeue_or_drop(
            get_redis(), MASTER_QUEUE_KEY, payload, self.logger,
            f"ArticleTable {master_sku} (network error)",
        )
