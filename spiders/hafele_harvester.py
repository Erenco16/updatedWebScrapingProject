"""
spiders/hafele_harvester.py  ── PRODUCER (sitemap + Selenium login)

Flow:
1. Log in to Hafele TR via Selenium Grid, capture session cookies
2. Push cookies to Redis (`hafele:session:cookies`) for processors to consume
3. Fetch sitemap index, extract every unique P-XXXXXX product-master ID
4. Queue master URLs (ViewProduct-Start?SKU=P-XXXXXX) into Redis
"""
import glob
import gzip
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis
import requests
from dotenv import load_dotenv

from database import reset_database
from spiders.headers import BROWSER_HEADERS, USER_AGENT
from src.hafele_login import login_and_get_cookies, save_cookies_to_redis
from src.send_mail import send_mail

DATA_DIR = os.getenv("DATA_DIR", "/app/data")

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://hafele-redis:6379")
REDIS_QUEUE_KEY = "hafele:api_urls"

GRID_URL = os.getenv("GRID_URL", "http://selenium-hub:4444/wd/hub")
HAFELE_USERNAME = os.getenv("hafele_username")
HAFELE_PASSWORD = os.getenv("hafele_password")

HAFELE_BASE = "https://www.hafele.com.tr"
SITEMAP_INDEX_URL = f"{HAFELE_BASE}/tr/sitemap.xml"
MASTER_URL_TEMPLATE = (
    f"{HAFELE_BASE}/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/"
    "ViewProduct-Start?SKU={sku}"
)

PRODUCT_URL_RE = re.compile(
    r"https://www\.hafele\.com\.tr/tr/product/[^<>\s\"]+?/P-(\d+)/"
)
SITEMAP_LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")


def get_redis():
    return redis.from_url(REDIS_URL, decode_responses=True)


def cleanup_stale_excel_files() -> int:
    """Remove any .xlsx files left over from previous runs.

    Only the most recent run's Excel should live in `DATA_DIR`. Non-.xlsx
    inputs (e.g. product_codes.xlsx if it were still used, .gitkeep, etc.)
    are left alone — we only touch `*_Hafele_Guncel_Stoklar.xlsx` files
    which are the reporter's output.
    """
    if not os.path.isdir(DATA_DIR):
        return 0
    pattern = os.path.join(DATA_DIR, "*_Hafele_Guncel_Stoklar.xlsx")
    removed = 0
    for path in glob.glob(pattern):
        try:
            os.remove(path)
            print(f"Removed stale Excel: {path}")
            removed += 1
        except OSError as e:
            print(f"Could not remove {path}: {e}")
    return removed


def send_start_notification() -> None:
    """Send a plain-text 'run started' email to informal_mail (if configured)."""
    informal_mail = (os.getenv("informal_mail") or "").strip()
    if not informal_mail:
        print("informal_mail not set; skipping start notification.")
        return
    started = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    body = (
        "Hafele veri toplama süreci başlatıldı.\n"
        f"Başlangıç zamanı: {started}\n\n"
        "The Hafele web scraping process has just started.\n"
        f"Started at: {started}"
    )
    try:
        send_mail(
            informal_mail,
            subject="🚀 Hafele Web Scraping Started",
            body=body,
        )
    except Exception as e:
        print(f"Could not send start notification: {e}")


def login_and_save_cookies(redis_client) -> dict:
    """Log in via Selenium Grid and persist cookies in Redis.

    Returns the harvested cookie dict so the caller can also use them for
    the sitemap fetch (helps with Cloudflare cf_clearance).
    """
    if not HAFELE_USERNAME or not HAFELE_PASSWORD:
        raise RuntimeError(
            "hafele_username / hafele_password env vars missing; API responses "
            "will be anonymous and stok_durumu will not be extractable."
        )

    print("Logging in via Selenium Grid...")
    cookies, logged_in = login_and_get_cookies(
        GRID_URL, USER_AGENT, HAFELE_USERNAME, HAFELE_PASSWORD
    )
    print(f"Captured {len(cookies)} cookies (logged_in_shape={logged_in})")
    save_cookies_to_redis(redis_client, cookies, USER_AGENT)
    if not logged_in:
        print(
            "WARNING: probe response does not look logged-in. Downstream API "
            "responses may still be anonymous. Check credentials / captcha."
        )
    return cookies


def fetch(url: str, cookies: dict | None = None) -> bytes:
    resp = requests.get(url, headers=BROWSER_HEADERS, cookies=cookies or {}, timeout=60)
    resp.raise_for_status()
    return resp.content


def load_sitemap_urls(index_url: str, cookies: dict | None = None) -> list:
    print(f"Fetching sitemap index: {index_url}")
    xml = fetch(index_url, cookies=cookies).decode("utf-8", errors="replace")
    urls = SITEMAP_LOC_RE.findall(xml)
    print(f"Found {len(urls)} sitemap file(s)")
    return urls


def extract_master_skus(sitemap_url: str, cookies: dict | None = None) -> set:
    print(f"Downloading sitemap: {sitemap_url[:120]}")
    body = fetch(sitemap_url, cookies=cookies)
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    text = body.decode("utf-8", errors="replace")
    skus = set(f"P-{m}" for m in PRODUCT_URL_RE.findall(text))
    print(f"Extracted {len(skus)} unique master SKUs from this sitemap")
    return skus


def push_master_urls(redis_client, skus: set) -> int:
    if not skus:
        return 0
    pipe = redis_client.pipeline()
    for sku in sorted(skus):
        url = MASTER_URL_TEMPLATE.format(sku=sku)
        pipe.lpush(REDIS_QUEUE_KEY, url)
    pipe.execute()
    return len(skus)


def main():
    print("=" * 60)
    print("HAFELE HARVESTER (Producer) - Login + Sitemap Mode")
    print("=" * 60)

    redis_client = get_redis()
    print(f"Redis connected: {REDIS_URL}")

    redis_client.delete(REDIS_QUEUE_KEY)
    print(f"Cleared old queue: {REDIS_QUEUE_KEY}")

    reset_database()
    cleanup_stale_excel_files()
    send_start_notification()

    try:
        cookies = login_and_save_cookies(redis_client)

        sitemap_files = load_sitemap_urls(SITEMAP_INDEX_URL, cookies=cookies)
        if not sitemap_files:
            print("No sitemap files referenced from index.")
            redis_client.set("hafele:harvester:status", "no_sitemaps")
            return

        all_skus = set()
        for url in sitemap_files:
            all_skus |= extract_master_skus(url, cookies=cookies)

        if not all_skus:
            print("No master SKUs extracted. Exiting.")
            redis_client.set("hafele:harvester:status", "no_skus")
            return

        pushed = push_master_urls(redis_client, all_skus)
        redis_client.set("hafele:harvester:total_masters", pushed)
        redis_client.set("hafele:harvester:status", "done")
        print(f"Harvester finished. {pushed} master URLs queued.")

    except Exception as e:
        print(f"Harvester error: {e}")
        import traceback
        traceback.print_exc()
        redis_client.set("hafele:harvester:status", f"error: {e}")
        raise


if __name__ == "__main__":
    main()
