"""Custom Selenium Grid middleware for Scrapy."""
import os
import time
import random
from scrapy.http import HtmlResponse
from scrapy import signals
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions

from spiders.headers import CHROME_ARGUMENTS, CHROME_EXPERIMENTAL_OPTIONS, USER_AGENT

SELENIUM_GRID_URL = os.getenv("SELENIUM_GRID_URL", "http://selenium-hub:4444/wd/hub")


# ─── Cloudflare Detection ────────────────────────────────────────

CHALLENGE_INDICATORS = [
    "Just a moment",
    "Checking your browser",
    "cf-browser-verification",
    "cf-im-under-attack",
    "challenge-platform",
    "__cf_chl_jschl_tk__",
    "cf-ray",
    "cloudflare",
]


def _is_challenge_page(html: str, title: str = "") -> bool:
    """Return True if the page is a Cloudflare challenge/interstitial."""
    combined = (html + " " + title).lower()
    return any(ind.lower() in combined for ind in CHALLENGE_INDICATORS)


class SeleniumGridMiddleware:
    """Scrapy middleware that routes requests through Selenium Grid for JS rendering."""

    def __init__(self, grid_url=None):
        self.grid_url = grid_url or SELENIUM_GRID_URL
        self.driver = None

    @classmethod
    def from_crawler(cls, crawler):
        grid_url = crawler.settings.get("SELENIUM_GRID_URL", SELENIUM_GRID_URL)
        mw = cls(grid_url=grid_url)
        crawler.signals.connect(mw.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(mw.spider_closed, signal=signals.spider_closed)
        return mw

    def spider_opened(self, spider):
        """Create a Selenium driver when spider opens."""
        spider.logger.info(f"Creating Selenium Grid driver: {self.grid_url}")
        chrome_options = ChromeOptions()

        # Anti-detection options from constants
        for arg in CHROME_ARGUMENTS:
            chrome_options.add_argument(arg)
        chrome_options.add_argument(f"--user-agent={USER_AGENT}")

        # Experimental options
        for key, value in CHROME_EXPERIMENTAL_OPTIONS.items():
            chrome_options.add_experimental_option(key, value)

        self.driver = webdriver.Remote(
            command_executor=self.grid_url,
            options=chrome_options,
        )

        # Stealth: remove webdriver property + patch plugins/languages
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-GB', 'en', 'tr']);
                    window.chrome = { runtime: {} };
                """
            }
        )

        spider.logger.info("Selenium Grid driver created")

    def _is_challenge_page(self, html: str) -> bool:
        title = ""
        try:
            title = self.driver.title or ""
        except Exception:
            pass
        return _is_challenge_page(html, title)

    def spider_closed(self, spider):
        """Quit Selenium driver when spider closes."""
        if self.driver:
            self.driver.quit()
            spider.logger.info("Selenium Grid driver quit")

    def process_request(self, request, spider):
        """
        Process requests marked for Selenium via meta['use_selenium'].
        Returns HtmlResponse with rendered page source.
        """
        if not request.meta.get("use_selenium", False):
            return None

        if not self.driver:
            spider.logger.error("Selenium driver not available")
            return None

        url = request.url
        spider.logger.info(f"[Selenium] Navigating: {url[:80]}...")

        # Human-like delay before navigation
        time.sleep(random.uniform(2, 5))
        self.driver.get(url)

        # Wait for page load
        wait_time = request.meta.get("wait_time", 10)
        wait_selector = request.meta.get("wait_for")
        if wait_selector:
            try:
                WebDriverWait(self.driver, wait_time).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
                )
            except Exception:
                spider.logger.warning(f"Timeout waiting for {wait_selector}")
        else:
            time.sleep(wait_time)

        # Add cookies if present
        if request.cookies:
            for name, value in request.cookies.items():
                self.driver.add_cookie({"name": name, "value": value})
            self.driver.get(url)
            time.sleep(random.uniform(2, 4))

        body_str = self.driver.page_source
        body = body_str.encode("utf-8")
        current_url = self.driver.current_url

        spider.logger.info(f"[Selenium] Page loaded: {len(body)} bytes, URL: {current_url[:80]}")

        # Detect Cloudflare challenge
        if _is_challenge_page(body_str):
            spider.logger.error(f"🚫 Cloudflare challenge detected at {current_url[:80]}")
            # Return a 503-like response so Scrapy will retry
            return HtmlResponse(
                url=current_url,
                body=body,
                encoding="utf-8",
                request=request,
                status=503,
            )

        return HtmlResponse(
            url=current_url,
            body=body,
            encoding="utf-8",
            request=request,
        )
