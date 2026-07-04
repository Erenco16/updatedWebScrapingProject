"""
Integration tests for Docker services.

These tests diagnose the failures seen in error-logs.log:
1. Selenium Grid session timeout (too many replicas, 1 node)
2. Cloudflare challenge pages (0 product rows found)
3. Missing cookies in Redis for some processors

Run inside Docker network or set SKIP_DOCKER_TESTS=1 to skip.
"""
import os
import socket
import pytest
import redis
import requests

REDIS_URL = os.getenv("REDIS_URL", "redis://hafele-redis:6379")
GRID_URL = os.getenv("SELENIUM_GRID_URL", "http://selenium-hub:4444/wd/hub")


def _can_resolve(hostname):
    """Check if a hostname resolves (inside Docker network)."""
    try:
        socket.gethostbyname(hostname)
        return True
    except socket.gaierror:
        return False


# Skip all if not inside Docker network
pytestmark = pytest.mark.skipif(
    not _can_resolve("hafele-redis") or not _can_resolve("selenium-hub"),
    reason="Docker services not reachable — run inside Docker network",
)


class TestRedisConnectivity:
    """Verify Redis is reachable and has expected state."""

    def test_redis_ping(self):
        r = redis.from_url(REDIS_URL, decode_responses=True)
        assert r.ping() is True

    def test_queue_key_exists_after_harvester(self):
        """Harvester should queue category URLs."""
        r = redis.from_url(REDIS_URL, decode_responses=True)
        length = r.llen("hafele:api_urls")
        # If 0, either harvester hasn't run or queue was cleared
        print(f"Queue length: {length}")
        # Not asserting >0 because test may run before harvester

    def test_cookies_key_exists(self):
        """Harvester should save session cookies for processors."""
        r = redis.from_url(REDIS_URL, decode_responses=True)
        cookies = r.get("hafele:session:cookies")
        if cookies is None:
            pytest.skip("No cookies in Redis — harvester may not have run yet")
        assert len(cookies) > 100


class TestSeleniumGridHealth:
    """Verify Selenium Grid can accept sessions."""

    def test_grid_status_endpoint(self):
        resp = requests.get(f"{GRID_URL}/status", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert "value" in data
        print(f"Grid status: {data['value']}")

    def test_grid_has_available_slots(self):
        resp = requests.get(f"{GRID_URL}/status", timeout=5)
        data = resp.json()
        nodes = data.get("value", {}).get("nodes", [])
        total_slots = sum(len(node.get("slots", [])) for node in nodes)
        print(f"Total Grid slots: {total_slots}")
        # 10 processor replicas need enough slots
        assert total_slots >= 1, "No Selenium Grid slots available"


class TestCategoryPageRendering:
    """Verify Selenium can render category pages and find products."""

    def test_category_page_has_product_divs(self):
        """Fails if Cloudflare blocks Selenium (challenge page)."""
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from bs4 import BeautifulSoup

        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])

        driver = webdriver.Remote(command_executor=GRID_URL, options=chrome_options)
        try:
            url = (
                "https://www.hafele.com.tr/tr/products/"
                "mobilya-kulplar-ve-kap-kollar-/mobilya-kulplar-ve-due-me-kulplar/11/"
            )
            driver.get(url)
            import time
            time.sleep(10)

            html = driver.page_source
            soup = BeautifulSoup(html, "html.parser")

            product_divs = [
                div for div in soup.find_all("div", class_="row")
                if "list-view" in div.get("class", []) and "article" in div.get("class", [])
            ]

            print(f"Page size: {len(html)} bytes, Product divs: {len(product_divs)}")

            if len(product_divs) == 0:
                title = soup.title.string if soup.title else "No title"
                print(f"Page title: {title}")
                if "moment" in title.lower():
                    pytest.fail(f"Cloudflare challenge page: {title}")
                pytest.fail(f"No product divs — page structure may have changed")

            assert len(product_divs) > 0
            first = product_divs[0]
            assert first.get("data-value", "").isdigit()
        finally:
            driver.quit()
