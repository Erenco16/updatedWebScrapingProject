"""
SQLite persistence pipeline for Scrapy items.

Pushes items onto Redis rather than writing to SQLite directly: 10
processor replicas writing to the same products.db file concurrently
(over a virtiofs-backed bind mount) silently lost a majority of writes
under load ("disk I/O error", "file is not a database") -- SQLite's WAL
mode depends on shared-memory lock coordination between writers that
doesn't reliably work across separate container mount namespaces here.
A single dedicated process (db_writer.py) drains this list and does every
write serially, which sidesteps the concurrent-writer problem entirely.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://hafele-redis:6379")
DB_WRITE_QUEUE_KEY = "hafele:db_write_queue"


class SQLitePipeline:
    """Scrapy 2.14+-compatible: process_item without the deprecated `spider` arg."""

    def __init__(self, crawler=None):
        self.crawler = crawler
        self.redis_client = redis.from_url(REDIS_URL, decode_responses=True)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler=crawler)

    def process_item(self, item):
        self.redis_client.lpush(DB_WRITE_QUEUE_KEY, json.dumps(dict(item)))
        return item
