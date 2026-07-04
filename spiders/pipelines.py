"""
SQLite persistence pipeline for Scrapy items.
"""
import sys
import os

# Ensure the repo root is on path so database.py is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import save_product


class SQLitePipeline:
    def process_item(self, item, spider):
        save_product(dict(item))
        return item
