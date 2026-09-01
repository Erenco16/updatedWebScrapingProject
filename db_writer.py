"""
db_writer.py

Single dedicated SQLite writer. The 10 processor replicas no longer write
to products.db directly -- concurrent writes from separate containers over
the virtiofs-backed ./data bind mount were silently failing ("disk I/O
error", "file is not a database") under load, since SQLite's WAL mode
depends on shared-memory lock coordination between writers that doesn't
reliably propagate across separate container mount namespaces on this kind
of filesystem. Consolidating every write into one process removes the
concurrent-writer scenario entirely, regardless of the underlying
filesystem's locking quirks.

Processors push each scraped item (JSON) onto REDIS_QUEUE_KEY; this process
blocks on that list and writes items to SQLite one at a time via
database.save_product().
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import redis

from database import save_product

REDIS_URL = os.getenv("REDIS_URL", "redis://hafele-redis:6379")
REDIS_QUEUE_KEY = "hafele:db_write_queue"
POP_TIMEOUT_SECONDS = 5


def main() -> None:
    # socket_timeout must exceed the BRPOP block time, or redis-py's own
    # socket read races the server-side blocking wait and raises
    # TimeoutError on every empty poll instead of returning None.
    rc = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=POP_TIMEOUT_SECONDS + 5)
    print(f"db-writer: connected to {REDIS_URL}, watching '{REDIS_QUEUE_KEY}'", flush=True)
    while True:
        try:
            popped = rc.brpop(REDIS_QUEUE_KEY, timeout=POP_TIMEOUT_SECONDS)
        except redis.exceptions.RedisError as e:
            print(f"db-writer: redis error, retrying: {e}", flush=True)
            continue
        if popped is None:
            continue
        _key, raw = popped
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"db-writer: dropping unparseable item: {e}", flush=True)
            continue
        save_product(item)


if __name__ == "__main__":
    main()
