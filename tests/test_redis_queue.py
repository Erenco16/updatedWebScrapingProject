"""
tests/test_redis_queue.py
Integration test suite for validating the new Harvester flow.

New flow:
- No login required
- Harvester navigates to global_one_pim_catalog
- Extracts accordion panel links (category URLs)
- Queues CATEGORY LINKS into Redis (not API URLs)
- Processors pop category URLs, extract SKUs with pagination,
  then fetch product data per SKU

Requirements:
    pip install pytest redis

Usage:
    REDIS_URL=redis://localhost:6379 pytest tests/test_redis_queue.py -v

Environment:
    REDIS_URL  (default: redis://localhost:6379/0)
"""
import os
import sys
import time
import subprocess

import pytest
import redis

# Allow importing project modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_KEY = "hafele:master_urls"
HARVESTER_STATUS_KEY = "hafele:harvester:status"
HARVESTER_TOTAL_KEY = "hafele:harvester:total_masters"


# ─── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def redis_client():
    """Provide a connected Redis client for the test module."""
    client = redis.from_url(REDIS_URL, decode_responses=True)

    # Verify connectivity
    try:
        client.ping()
    except redis.ConnectionError as exc:
        pytest.fail(
            f"Cannot connect to Redis at {REDIS_URL}. "
            f"Is the Redis container running? Error: {exc}"
        )

    yield client

    # Cleanup: flush test keys after tests
    client.delete(QUEUE_KEY, HARVESTER_STATUS_KEY, HARVESTER_TOTAL_KEY)


@pytest.fixture
def run_harvester(redis_client):
    """Run the harvester spider and wait for completion."""
    # Ensure queue is empty before run
    redis_client.delete(QUEUE_KEY, HARVESTER_STATUS_KEY, HARVESTER_TOTAL_KEY)

    # Run harvester as subprocess
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    harvester_module = "spiders.hafele_harvester"

    py = sys.executable
    print(f"\n🚀 Starting harvester: {py} -m {harvester_module}")

    env = os.environ.copy()
    env["REDIS_URL"] = REDIS_URL

    proc = subprocess.Popen(
        [py, "-m", harvester_module],
        cwd=project_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Wait for harvester to finish (with timeout)
    try:
        stdout, _ = proc.communicate(timeout=300)  # 5 minutes max
        print(stdout)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("Harvester timed out after 5 minutes")

    if proc.returncode != 0:
        pytest.fail(f"Harvester exited with code {proc.returncode}\nOutput:\n{stdout}")

    # Give Redis a moment to settle
    time.sleep(1)

    return stdout


# ─── Test Cases ──────────────────────────────────────────────────────

class TestRedisQueue:
    """Validate that the harvester correctly populates the Redis queue with master product URLs."""

    def test_queue_not_empty(self, redis_client, run_harvester):
        """Assert the Redis queue contains at least one master URL."""
        queue_len = redis_client.llen(QUEUE_KEY)

        assert queue_len > 0, (
            f"Redis queue '{QUEUE_KEY}' is EMPTY. "
            f"The harvester did not push any master URLs. "
            f"Possible causes:\n"
            f"  1. Cloudflare blocked the sitemap request\n"
            f"  2. Sitemap format changed (no <loc> tags)\n"
            f"  3. Sitemap contains no /tr/product/*/P-XXXXXX/ URLs"
        )

    def test_queue_has_many_items(self, redis_client, run_harvester):
        """Sitemap should yield thousands of master URLs."""
        queue_len = redis_client.llen(QUEUE_KEY)

        assert queue_len > 100, (
            f"Sitemap extraction may have failed. "
            f"The harvester queued only {queue_len} master URL(s), "
            f"expected >>100 from the Turkish sitemap."
        )

    def test_queue_items_are_valid_master_urls(self, redis_client, run_harvester):
        """Assert each queue item is a JSON envelope wrapping a valid
        master ViewProduct-Start URL (see spiders/hafele_parsing.py)."""
        import json
        import re

        items = redis_client.lrange(QUEUE_KEY, 0, -1)
        assert len(items) > 0, "Queue is empty"

        url_pattern = re.compile(
            r"^https://www\.hafele\.com\.tr/prod-live/web/WFS/Haefele-HTR-Site/"
            r"tr_TR/-/TRY/ViewProduct-Start\?SKU=P-\d+$"
        )

        invalid_items = []
        for item in items:
            try:
                url = json.loads(item)["url"]
            except (json.JSONDecodeError, KeyError, TypeError):
                invalid_items.append(item[:120])
                continue
            if not url_pattern.match(url):
                invalid_items.append(item[:120])

        assert len(invalid_items) == 0, (
            f"Found {len(invalid_items)} invalid URL(s) in queue.\n"
            f"Queue should contain master URLs like: "
            f"https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-Start?SKU=P-XXXXXXXX\n"
            f"First 5 invalid items:\n" +
            "\n".join(f"  - {item}" for item in invalid_items[:5])
        )

    def test_harvester_status_is_done(self, redis_client, run_harvester):
        """Assert harvester recorded a 'done' status in Redis."""
        status = redis_client.get(HARVESTER_STATUS_KEY)

        assert status == "done", (
            f"Harvester status is '{status}', expected 'done'. "
            f"The harvester may have crashed or been interrupted."
        )

    def test_total_categories_match_queue_length(self, redis_client, run_harvester):
        """Assert the recorded total matches actual queue length."""
        queue_len = redis_client.llen(QUEUE_KEY)
        recorded_total = redis_client.get(HARVESTER_TOTAL_KEY)

        assert recorded_total is not None, (
            f"Missing '{HARVESTER_TOTAL_KEY}' key in Redis. "
            f"Harvester did not record its summary."
        )

        recorded_total = int(recorded_total)
        assert recorded_total == queue_len, (
            f"Mismatch: recorded total ({recorded_total}) != "
            f"actual queue length ({queue_len}). "
            f"Some category links may have been lost or duplicated."
        )


class TestRedisConnection:
    """Basic connectivity tests."""

    def test_redis_ping(self, redis_client):
        """Redis server responds to ping."""
        assert redis_client.ping() is True

    def test_redis_can_write_and_read(self, redis_client):
        """Redis can perform basic write/read/delete."""
        test_key = "hafele:test:ping"
        test_value = "pong"

        redis_client.set(test_key, test_value, ex=5)
        retrieved = redis_client.get(test_key)

        assert retrieved == test_value

        redis_client.delete(test_key)
        assert redis_client.get(test_key) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
