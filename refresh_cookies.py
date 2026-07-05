"""
refresh_cookies.py

Long-running sidecar that re-logs in to Hafele TR every N seconds and
updates the session cookies in Redis. Downstream processors read the
updated cookies via `spiders.middlewares.RedisCookieMiddleware` on a
60-second in-process cache, so no processor restart is needed when the
cookies rotate.

Environment variables:
  REDIS_URL                    Redis connection string
                               (default: redis://hafele-redis:6379)
  GRID_URL                     Selenium Grid hub URL
                               (default: http://selenium-hub:4444/wd/hub)
  hafele_username              Hafele login username
  hafele_password              Hafele login password
  COOKIE_REFRESH_INTERVAL      Seconds between refreshes
                               (default: 600 = 10 minutes)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import redis
from dotenv import load_dotenv

from spiders.headers import USER_AGENT
from src.hafele_login import login_and_get_cookies, save_cookies_to_redis

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://hafele-redis:6379")
GRID_URL = os.getenv("GRID_URL", "http://selenium-hub:4444/wd/hub")
HAFELE_USERNAME = os.getenv("hafele_username")
HAFELE_PASSWORD = os.getenv("hafele_password")
INTERVAL = int(os.getenv("COOKIE_REFRESH_INTERVAL", "600"))


def _refresh(rc) -> bool:
    try:
        cookies, ok = login_and_get_cookies(
            GRID_URL, USER_AGENT, HAFELE_USERNAME, HAFELE_PASSWORD
        )
    except Exception as e:
        print(f"cookie-refresher: login FAILED: {e}", flush=True)
        return False
    save_cookies_to_redis(rc, cookies, USER_AGENT)
    print(
        f"cookie-refresher: refreshed {len(cookies)} cookies "
        f"(logged_in_shape={ok})",
        flush=True,
    )
    return ok


def main() -> None:
    if not HAFELE_USERNAME or not HAFELE_PASSWORD:
        raise RuntimeError(
            "hafele_username / hafele_password env vars are required"
        )
    print(
        f"cookie-refresher: connecting to {REDIS_URL}; "
        f"grid={GRID_URL}; interval={INTERVAL}s",
        flush=True,
    )
    rc = redis.from_url(REDIS_URL, decode_responses=True)

    # Wait a beat so we don't fight the harvester for a Grid slot on cold start.
    time.sleep(30)

    while True:
        _refresh(rc)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
