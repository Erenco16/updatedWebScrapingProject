"""
SQLite persistence pipeline for Scrapy items.
"""
import os
import sys

# Ensure the repo root is on path so database.py is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import save_product


class SQLitePipeline:
    """Scrapy 2.14+-compatible: process_item without the deprecated `spider` arg."""

    def __init__(self, crawler=None):
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler=crawler)

    def process_item(self, item):
        save_product(dict(item))
        return item
