"""
spiders/hafele_harvester.py  ── PRODUCER (sitemap + Selenium login)

Flow:
1. Log in to Hafele TR via Selenium Grid, capture session cookies
2. Push cookies to Redis (`hafele:session:cookies`) for processors to consume
3. Fetch sitemap index, extract every unique P-XXXXXX product-master ID
4. Queue master URLs (ViewProduct-Start?SKU=P-XXXXXX) into Redis
"""
import gzip
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis
import requests
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

from database import reset_database
from spiders.headers import BROWSER_HEADERS, USER_AGENT

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://hafele-redis:6379")
REDIS_QUEUE_KEY = "hafele:api_urls"
REDIS_COOKIES_KEY = "hafele:session:cookies"

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


def _driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(f"--user-agent={USER_AGENT}")
    return webdriver.Remote(command_executor=GRID_URL, options=opts)


def login_and_save_cookies(redis_client) -> dict:
    """Log in to Hafele TR through Grid and store the resulting cookies in Redis.

    Returns the harvested cookie dict (name -> value) so the caller can also
    use them for the sitemap fetch (they help with Cloudflare cf_clearance).
    """
    if not HAFELE_USERNAME or not HAFELE_PASSWORD:
        raise RuntimeError(
            "hafele_username / hafele_password env vars missing; API responses "
            "will be anonymous and stok_durumu will not be extractable."
        )

    print("Logging in via Selenium Grid...")
    d = _driver()
    try:
        d.get(f"{HAFELE_BASE}/")
        time.sleep(5)

        # OneTrust cookie banner
        d.execute_script(
            "var b=document.getElementById('onetrust-accept-btn-handler'); if(b) b.click();"
        )
        time.sleep(1)

        # Country modal: click the SECONDARY (stay-here) button, not the primary redirect one
        d.execute_script(
            "var b=document.querySelector('a.modal-link.t-btn-secondary,button.modal-link.t-btn-secondary');"
            " if(b) b.click();"
        )
        time.sleep(2)

        # Open header login modal
        d.execute_script("document.getElementById('headerLoginLinkAction').click();")
        time.sleep(2)

        d.find_element(By.ID, "ShopLoginForm_Login_headerItemLogin").send_keys(HAFELE_USERNAME)
        d.find_element(By.ID, "ShopLoginForm_Password_headerItemLogin").send_keys(HAFELE_PASSWORD)
        try:
            d.execute_script(
                "var b=document.getElementById('divShopLoginForm_RememberLogin_headerItemLogin'); if(b) b.click();"
            )
        except Exception:
            pass
        time.sleep(1)

        d.execute_script(
            "document.querySelector('button[data-testid=\"ajaxAccountLoginFormBtn\"]').click();"
        )
        # Give the ajax login + session hydration time to settle
        time.sleep(12)

        # Sanity: probe the API in-browser to make sure cookies are logged-in-state
        probe = d.execute_async_script(
            "var cb=arguments[arguments.length-1];"
            "fetch('/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/"
            "ViewProduct-GetPriceAndAvailabilityInformationPDS?SKU=82645712&ProductQuantity=20000&SynchronizationAjaxToken=1',"
            "{credentials:'include', headers:{'X-Requested-With':'XMLHttpRequest'}})"
            ".then(r=>r.text()).then(cb).catch(e=>cb('ERR:'+e));"
        )
        logged_in = "values-tr" in (probe or "") or "availability-flag" in (probe or "")
        print(
            f"Login probe: response_len={len(probe or '')}, "
            f"logged_in_shape={logged_in}"
        )

        cookies = d.get_cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies if c.get("name") and c.get("value") is not None}
        print(f"Captured {len(cookie_dict)} cookies")
        redis_client.set(REDIS_COOKIES_KEY, json.dumps(cookie_dict))
        redis_client.set(REDIS_COOKIES_KEY + ":user_agent", USER_AGENT)
        if not logged_in:
            print(
                "WARNING: probe response does not look logged-in. Downstream API "
                "responses may still be anonymous. Check credentials / captcha."
            )
        return cookie_dict
    finally:
        try:
            d.quit()
        except Exception:
            pass


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
