"""
tests/test_queue.py

Unit-level coverage of every Redis-queue code path we rely on:
- harvester pushing master URLs
- scraper spider's SQLitePipeline enqueuing items to db-writer
- discovery/scraper requeue_or_drop semantics (attempt vs. net_attempt caps)
- db-writer-shaped BRPOP consumer loop

All backed by ``fakeredis`` so the suite runs anywhere — no docker-compose
up, no reachable Redis host. The existing ``test_redis_queue.py`` already
covers the live-Redis integration path; this file is the fast feedback
loop that catches queue regressions during normal development.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from unittest.mock import patch

import fakeredis
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spiders.hafele_parsing import (
    MASTER_QUEUE_KEY,
    SCRAPE_QUEUE_KEY,
    MAX_ATTEMPTS,
    MAX_NET_ATTEMPTS,
    requeue_or_drop,
    build_api_url,
)


@pytest.fixture
def rc():
    """A fresh fakeredis client per test."""
    return fakeredis.FakeStrictRedis(decode_responses=True)


# ─── requeue_or_drop ────────────────────────────────────────────

class TestRequeueOrDrop:
    def test_application_attempt_increments(self, rc):
        payload = {"url": "https://x/", "attempt": 0}
        requeue_or_drop(rc, SCRAPE_QUEUE_KEY, payload, logging.getLogger(), "test")
        assert rc.llen(SCRAPE_QUEUE_KEY) == 1
        requeued = json.loads(rc.rpop(SCRAPE_QUEUE_KEY))
        assert requeued["attempt"] == 1
        assert requeued["url"] == payload["url"]

    def test_application_attempt_cap_drops_payload(self, rc):
        payload = {"url": "https://x/", "attempt": MAX_ATTEMPTS}
        requeue_or_drop(rc, SCRAPE_QUEUE_KEY, payload, logging.getLogger(), "test")
        # already at MAX_ATTEMPTS -> next increment exceeds -> dropped
        assert rc.llen(SCRAPE_QUEUE_KEY) == 0

    def test_network_attempt_uses_separate_counter(self, rc):
        """The whole point of count_attempt=False: a bad network window
        must not consume the application attempt budget."""
        payload = {"url": "https://x/", "attempt": 0}
        for _ in range(MAX_NET_ATTEMPTS):
            raw = rc.rpop(SCRAPE_QUEUE_KEY)
            if raw:
                payload = json.loads(raw)
            requeue_or_drop(
                rc, SCRAPE_QUEUE_KEY, payload, logging.getLogger(),
                "test", count_attempt=False,
            )
        # Still exactly one item, net_attempt == MAX
        assert rc.llen(SCRAPE_QUEUE_KEY) == 1
        last = json.loads(rc.rpop(SCRAPE_QUEUE_KEY))
        assert last["net_attempt"] == MAX_NET_ATTEMPTS
        assert last.get("attempt", 0) == 0  # untouched

    def test_network_attempt_cap_drops_payload(self, rc):
        payload = {"url": "https://x/", "net_attempt": MAX_NET_ATTEMPTS}
        requeue_or_drop(
            rc, SCRAPE_QUEUE_KEY, payload, logging.getLogger(),
            "test", count_attempt=False,
        )
        assert rc.llen(SCRAPE_QUEUE_KEY) == 0


# ─── Harvester push_master_urls ─────────────────────────────────

class TestHarvesterPush:
    def test_push_master_urls_queues_json_payloads(self, rc):
        from spiders import hafele_harvester

        skus = {"P-00000001", "P-00000002", "P-00000003"}
        pushed = hafele_harvester.push_master_urls(rc, skus)
        assert pushed == 3
        assert rc.llen(MASTER_QUEUE_KEY) == 3
        items = [json.loads(x) for x in rc.lrange(MASTER_QUEUE_KEY, 0, -1)]
        # Every item is a valid payload shape
        for item in items:
            assert set(item) == {"url", "attempt"}
            assert item["attempt"] == 0
            assert item["url"].startswith("https://www.hafele.com.tr/")
            assert "ViewProduct-Start?SKU=P-" in item["url"]

    def test_push_master_urls_is_sorted_deterministic(self, rc):
        """Harvester sorts SKUs before pushing so queue order is
        reproducible across runs; important for comparison tests."""
        from spiders import hafele_harvester

        hafele_harvester.push_master_urls(rc, {"P-9", "P-1", "P-5"})
        # LPUSH in sorted order means RPOP yields in the sorted order
        a = json.loads(rc.rpop(MASTER_QUEUE_KEY))
        b = json.loads(rc.rpop(MASTER_QUEUE_KEY))
        c = json.loads(rc.rpop(MASTER_QUEUE_KEY))
        assert "SKU=P-1" in a["url"]
        assert "SKU=P-5" in b["url"]
        assert "SKU=P-9" in c["url"]


# ─── SQLitePipeline → db-writer handoff ─────────────────────────

class TestSqlitePipeline:
    def test_process_item_enqueues_json(self, rc):
        from spiders import pipelines

        with patch.object(pipelines, "redis") as redis_mod:
            redis_mod.from_url.return_value = rc
            pipe = pipelines.SQLitePipeline.from_crawler(crawler=None)

        item = {
            "sku": "90198256",
            "stock_code": "90198256",
            "stok_durumu": "stokta mevcut",
            "stock_amount": 35,
        }
        pipe.process_item(item)

        assert rc.llen(pipelines.DB_WRITE_QUEUE_KEY) == 1
        popped = json.loads(rc.rpop(pipelines.DB_WRITE_QUEUE_KEY))
        assert popped["sku"] == "90198256"
        assert popped["stock_amount"] == 35


# ─── Consumer loop (db-writer-shaped BRPOP) ─────────────────────

class TestConsumerLoop:
    def test_brpop_drains_pushed_items_in_fifo_order(self, rc):
        """LPUSH + BRPOP from the opposite end gives FIFO — this is
        what db_writer.main relies on."""
        payloads = [{"sku": f"0000000{i}", "qty": i} for i in range(5)]
        for p in payloads:
            rc.lpush("hafele:db_write_queue", json.dumps(p))

        got = []
        for _ in range(len(payloads)):
            key, raw = rc.brpop("hafele:db_write_queue", timeout=1)
            assert key == "hafele:db_write_queue"
            got.append(json.loads(raw))

        assert got == payloads
        # Queue is empty after draining
        assert rc.llen("hafele:db_write_queue") == 0

    def test_brpop_returns_none_on_empty_queue(self, rc):
        """BRPOP with a short timeout on an empty queue returns None,
        which db_writer.main treats as "idle, try again"."""
        assert rc.brpop("hafele:db_write_queue", timeout=1) is None

    def test_end_to_end_produce_then_consume(self, rc):
        """Full round trip: harvester queues → consumer drains →
        pipeline forwards → db-writer loop sees it."""
        from spiders import hafele_harvester, pipelines

        # 1. Harvester queues 3 master URLs
        hafele_harvester.push_master_urls(rc, {"P-A", "P-B"})
        assert rc.llen(MASTER_QUEUE_KEY) == 2

        # 2. Discovery-shaped consumer pops a master, synthesises a
        #    variant API URL, pushes onto scrape queue
        raw = rc.rpop(MASTER_QUEUE_KEY)
        payload = json.loads(raw)
        assert "ViewProduct-Start?SKU=P-" in payload["url"]
        rc.lpush(SCRAPE_QUEUE_KEY, json.dumps({"url": build_api_url("90198256"), "attempt": 0}))

        # 3. Scraper-shaped consumer pops the variant and yields an item
        raw = rc.rpop(SCRAPE_QUEUE_KEY)
        api_payload = json.loads(raw)
        assert "SKU=90198256" in api_payload["url"]

        # 4. Pipeline forwards item to db-writer queue
        with patch.object(pipelines, "redis") as redis_mod:
            redis_mod.from_url.return_value = rc
            pipe = pipelines.SQLitePipeline.from_crawler(crawler=None)
        pipe.process_item({"sku": "90198256", "stock_amount": 42})

        # 5. db-writer-shaped BRPOP drains it
        key, raw = rc.brpop(pipelines.DB_WRITE_QUEUE_KEY, timeout=1)
        final = json.loads(raw)
        assert final["sku"] == "90198256"
        assert final["stock_amount"] == 42
        assert rc.llen(pipelines.DB_WRITE_QUEUE_KEY) == 0
