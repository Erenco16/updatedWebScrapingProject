"""
Scrapy-Redis settings for the distributed Hafele scraper.
"""
import os

BOT_NAME = "hafele_scraper"
SPIDER_MODULES = ["spiders"]
NEWSPIDER_MODULE = "spiders"

# ─── Redis Scheduler ───
SCHEDULER = "scrapy_redis.scheduler.Scheduler"
DUPEFILTER_CLASS = "scrapy_redis.dupefilter.RFPDupeFilter"
SCHEDULER_PERSIST = True  # Keep queue between restarts
SCHEDULER_FLUSH_ON_START = False

REDIS_URL = os.getenv("REDIS_URL", "redis://hafele-redis:6379")

# ─── Throughput ───
CONCURRENT_REQUESTS = 16
DOWNLOAD_DELAY = 1.0
RANDOMIZE_DOWNLOAD_DELAY = 0.5

# ─── Retry / Middleware ───
RETRY_TIMES = 5
RETRY_HTTP_CODES = [403, 429, 500, 502, 503, 504]

# Keep user-agent from env
DEFAULT_REQUEST_HEADERS = {
    "User-Agent": os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Logging
LOG_LEVEL = "INFO"

# Auto-close spider when no new items from Redis for 60 seconds
SCHEDULER_IDLE_BEFORE_CLOSE = 60

# Pipelines
ITEM_PIPELINES = {
    "spiders.pipelines.SQLitePipeline": 300,
}

DOWNLOADER_MIDDLEWARES = {
    "scrapy.downloadermiddlewares.retry.RetryMiddleware": 90,
}
