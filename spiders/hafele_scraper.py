"""
spiders/hafele_scraper.py  ── SCRAPER (Scrapy-Redis Spider)

Pops variant price/stock API URLs from hafele:scrape_queue (pushed by the
separate discovery spider, spiders/hafele_discovery.py), fetches real
price/stock data, and yields the item for spiders.pipelines.SQLitePipeline
to hand off to db_writer.py. Runs as its own set of containers,
concurrently with the discovery pool.

Dinler stock-fallback flow (new): whenever Hafele's own availability
endpoint can't tell us anything (``stok_durumu == DEFAULT_STATUS_UNKNOWN``),
instead of writing "Stok bilgisi bulunamadi" we yield a follow-up Request
to Dinler Mobilya's public stock API, parse the JSON reply, and merge the
``stockAmount`` / ``message`` fields into the item before yielding it to
the pipeline. The follow-up goes through the same Scrapling-backed
downloader middleware as the primary scrape, so it also benefits from
IPv4 forcing and the connect-error retry window.
"""
import json

from pydantic import ValidationError
from scrapy import Request
from scrapy_redis.spiders import RedisSpider

from spiders.headers import API_HEADERS
from spiders.models import ProductItem, format_sku_with_dots
from spiders.dinler_log import log_fallback_attempt
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
    build_dinler_url,
    normalize_stock_status,
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
            "spiders.middlewares.ScraplingDownloadMiddleware": 150,
        },
    }

    _DINLER_HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "tr,en-US;q=0.9,en;q=0.8",
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

    # ─── Hafele price + stock parse ─────────────────────────────

    def parse_product_api(self, response):
        payload = response.meta["payload"]
        api_url = payload["url"]
        sku_m = API_SKU_RE.search(api_url)
        sku = sku_m.group(1) if sku_m else ""

        if response.status != 200:
            self.logger.warning(f"API SKU={sku} status {response.status}")
            requeue_or_drop(get_redis(), SCRAPE_QUEUE_KEY, payload, self.logger, f"API SKU={sku}")
            return

        # Scrapling-backed parsing: see spiders/hafele_parsing.py.
        stok_durumu, stock_amount = parse_stock_from_values_tr(response.body)
        if not stok_durumu:
            stok_durumu = parse_stock_fallback(response.body) or DEFAULT_STATUS_UNKNOWN

        price_info = parse_price_from_html(response.body)

        redis_client = get_redis()
        meta_json = redis_client.hget(REDIS_META_HASH, sku)
        master_meta = json.loads(meta_json) if meta_json else {}
        name = master_meta.get("name") or master_meta.get("meta_description") or ""
        description = name
        if master_meta.get("subline"):
            description = f"{description} | {master_meta['subline']}".strip(" |")

        item_payload = dict(
            sku=sku,
            stock_code=sku,
            product_name=name or None,
            product_description=description or "",
            kdv_haric_net_fiyat=price_info.get("kdv_haric_net_fiyat"),
            kdv_haric_tavsiye_edilen_perakende_fiyat=price_info.get(
                "kdv_haric_tavsiye_edilen_perakende_fiyat"
            ),
            kdv_haric_satis_fiyati=price_info.get("kdv_haric_satis_fiyati"),
            currency="TRY",
            stok_durumu=stok_durumu,
            stock_amount=stock_amount,
            stock_status=normalize_stock_status(stok_durumu, stock_amount),
            is_group_product=0,
        )

        try:
            item = ProductItem(**item_payload)
        except ValidationError as e:
            self.logger.error(f"API SKU={sku} ProductItem validation failed: {e}")
            return

        self.logger.info(
            f"API SKU={sku} status='{item.stok_durumu}' qty={item.stock_amount}"
        )

        # Hafele has no useful stock info for this variant → ask Dinler.
        # Yield a follow-up Request rather than blocking inside this
        # callback; downloader middleware will run it in a worker thread
        # like every other request.
        if item.stok_durumu == DEFAULT_STATUS_UNKNOWN:
            dinler_url = build_dinler_url(sku)
            self.logger.info(f"Dinler fallback → {dinler_url}")
            yield Request(
                url=dinler_url,
                callback=self.parse_dinler_fallback,
                errback=self.on_dinler_failure,
                meta={"item": item.model_dump(), "sku": sku},
                dont_filter=True,
                headers=self._DINLER_HEADERS,
            )
            return

        yield item.model_dump()

    # ─── Dinler stock-fallback branch ──────────────────────────

    def parse_dinler_fallback(self, response):
        item_data = response.meta["item"]
        sku = response.meta.get("sku") or item_data.get("sku", "?")

        try:
            payload = json.loads(response.text) if response.body else {}
        except (ValueError, UnicodeDecodeError) as e:
            self.logger.warning(f"Dinler SKU={sku} unparseable JSON: {e}")
            log_fallback_attempt(sku, "parse_error", error=e, status=response.status)
            yield item_data
            return

        if response.status != 200:
            msg = payload.get("message") or payload.get("quantityError") or f"HTTP {response.status}"
            self.logger.info(f"Dinler SKU={sku} http_error {response.status}: {msg}")
            log_fallback_attempt(sku, "http_error", status=response.status, message=msg)
            yield item_data
            return

        if not payload.get("success"):
            msg = payload.get("message") or payload.get("quantityError") or "no success flag"
            self.logger.info(f"Dinler SKU={sku} miss: {msg}")
            log_fallback_attempt(sku, "miss", message=msg)
            yield item_data
            return

        message = payload.get("message")
        state = payload.get("state")
        new_stok = message or state or item_data.get("stok_durumu")
        new_amt = payload.get("stockAmount", item_data.get("stock_amount"))

        item_data["stok_durumu"] = new_stok
        item_data["stock_amount"] = new_amt
        item_data["stock_status"] = normalize_stock_status(new_stok, new_amt)
        self.logger.info(
            f"Dinler SKU={format_sku_with_dots(sku)} resolved: "
            f"status='{new_stok}' qty={new_amt}"
        )
        log_fallback_attempt(
            sku, "resolved",
            state=state, stock_amount=new_amt, message=message,
        )
        yield item_data

    def on_dinler_failure(self, failure):
        """Dinler is best-effort: on transport failure, still ship the
        item with its original (unknown) stock info so we don't lose
        the row entirely."""
        item_data = failure.request.meta.get("item", {})
        sku = failure.request.meta.get("sku", "?")
        self.logger.warning(f"Dinler SKU={sku} fallback transport failed: {failure.value}")
        err = getattr(failure, "value", None) or Exception(str(failure))
        log_fallback_attempt(sku, "transport_error", error=err)
        if item_data:
            yield item_data

    # ─── Primary request errback ───────────────────────────────

    def on_failure(self, failure):
        payload = failure.request.meta["payload"]
        sku_m = API_SKU_RE.search(payload["url"])
        sku = sku_m.group(1) if sku_m else "?"
        self.logger.warning(f"API SKU={sku} request failed: {failure.value}")
        # Transport failure — don't burn an application attempt.
        requeue_or_drop(
            get_redis(), SCRAPE_QUEUE_KEY, payload, self.logger,
            f"API SKU={sku} (network error)", count_attempt=False,
        )
