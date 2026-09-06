"""Custom Scrapy middlewares.

- SeleniumGridMiddleware: legacy JS-render fallback (currently unused).
- RedisCookieMiddleware: pulls fresh session cookies from Redis on a short
  TTL and attaches them to every request. Pairs with the cookie-refresher
  sidecar so long-running processors don't drift onto expired sessions.
- RequestsDownloadMiddleware: fetch via python-requests in a worker thread
  instead of Twisted's built-in HTTP client. Cloudflare fingerprints and
  blocks Twisted's TLS/connection stack on this site even with identical
  cookies/headers that pass through requests, curl, and a real browser.
"""
import json
import os
import time
import random
import redis
import socket
import urllib3.util.connection as _urllib3_connection
import requests as py_requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from scrapy.http import HtmlResponse
from scrapy import signals
from twisted.internet.threads import deferToThread

# Force IPv4 for all urllib3-backed requests (requests library).
# The Docker network on this host only routes IPv4 outbound reliably;
# getent returns AAAA records for hafele.com.tr, and requests then tries
# IPv6 first and can fail immediately with "Network is unreachable"
# (especially during the first seconds after a container starts).
# Twisted's HTTP client happened to fall back to IPv4 on its own.
_urllib3_connection.allowed_gai_family = lambda: socket.AF_INET


def _make_requests_session() -> py_requests.Session:
    """A Session with urllib3-level retries for connect/read errors only.

    We deliberately do NOT retry HTTP status codes here — Scrapy's
    RetryMiddleware already handles RETRY_HTTP_CODES on the returned
    Response. Retrying connect/read errors here prevents a brief network
    hiccup (e.g. right at container startup) from being counted as a
    request "attempt" against the payload's 3-attempt cap, which
    otherwise burns through the whole queue in seconds.
    """
    retry = Retry(
        total=5,
        connect=5,
        read=3,
        status=0,
        backoff_factor=1.0,       # sleeps: 0, 1, 2, 4, 8 seconds
        status_forcelist=[],
        raise_on_status=False,
        allowed_methods=frozenset(["GET", "POST", "HEAD"]),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=32, pool_maxsize=32)
    sess = py_requests.Session()
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess


_SESSION = _make_requests_session()
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


# ─── Redis-backed cookie injection ────────────────────────────────

class RedisCookieMiddleware:
    """Attach fresh session cookies from Redis to every outgoing request.

    Reads `hafele:session:cookies` (JSON), caches the result in-process for
    `COOKIE_CACHE_TTL` seconds (default 60), and sets `request.cookies` so
    Scrapy's built-in CookiesMiddleware (higher priority) serialises them
    into the Cookie header.

    Pair with the `cookie-refresher` sidecar, which re-logs in every 10 min
    and updates the same Redis key. Processors then automatically pick up
    the new cookies within one TTL window without needing to restart.
    """

    def __init__(self, crawler, redis_url: str, cache_ttl: int, cookies_key: str):
        # Stash crawler so we can get the current spider without receiving it
        # as a process_request argument (removed in Scrapy 2.14+).
        self.crawler = crawler
        self.redis_url = redis_url
        self.cache_ttl = cache_ttl
        self.cookies_key = cookies_key
        self._cookies: dict = {}
        self._last_refresh = 0.0
        self._redis = None

    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        return cls(
            crawler=crawler,
            redis_url=os.getenv("REDIS_URL", settings.get("REDIS_URL", "redis://hafele-redis:6379")),
            cache_ttl=int(settings.getint("COOKIE_CACHE_TTL", 60)),
            cookies_key=settings.get("COOKIE_REDIS_KEY", "hafele:session:cookies"),
        )

    def _get_redis(self):
        if self._redis is None:
            self._redis = redis.from_url(self.redis_url, decode_responses=True)
        return self._redis

    def _maybe_refresh(self):
        now = time.time()
        if now - self._last_refresh < self.cache_ttl:
            return
        spider = self.crawler.spider
        try:
            raw = self._get_redis().get(self.cookies_key)
            if not raw:
                self._last_refresh = now
                return
            self._cookies = json.loads(raw) or {}
            self._last_refresh = now
            if spider is not None:
                spider.logger.debug(f"[cookies] refreshed cache: {len(self._cookies)} cookies")
        except Exception as e:
            if spider is not None:
                spider.logger.warning(f"[cookies] refresh failed: {e}")

    def process_request(self, request):
        self._maybe_refresh()
        if not self._cookies:
            return None
        # Merge — request-level cookies (rarely used here) take priority.
        current = dict(request.cookies) if isinstance(request.cookies, dict) else {}
        merged = dict(self._cookies)
        merged.update(current)
        request.cookies = merged
        return None


# ─── Cloudflare-safe fetch via python-requests ────────────────────

class RequestsDownloadMiddleware:
    """Fetch every request via python-requests in a worker thread instead of
    Twisted's built-in HTTP client.

    Twisted's TLS/connection stack gets fingerprinted and blocked by
    Cloudflare on this site even with byte-identical cookies/headers that
    pass fine through requests, curl, and a real browser (confirmed by
    testing all four directly). This middleware swaps out only the actual
    bytes-on-the-wire fetch; the returned Response flows through Scrapy's
    normal pipeline (RetryMiddleware, item pipeline, spider callbacks)
    unchanged.

    Register at a priority AFTER RedisCookieMiddleware (100) — e.g. 150 —
    so cookies are already merged onto request.cookies before we fetch,
    and so Scrapy's built-in CookiesMiddleware (700) is short-circuited
    (returning a Response from process_request stops the chain).
    """

    # Response headers requests has already consumed on our behalf; leaving
    # them in place makes Scrapy's HttpCompressionMiddleware try to gunzip
    # an already-decompressed body ("Not a gzipped file" error).
    _STRIP_RESPONSE_HEADERS = {"content-encoding", "content-length", "transfer-encoding"}

    def __init__(self, timeout: float):
        self.timeout = timeout

    @classmethod
    def from_crawler(cls, crawler):
        return cls(timeout=crawler.settings.getfloat("DOWNLOAD_TIMEOUT", 60))

    def process_request(self, request, spider):
        # Run blocking requests.request in a thread so we don't stall the
        # Scrapy/Twisted reactor. Returning a Deferred is soft-deprecated
        # but still supported; the `async def` variant fails under
        # Scrapy's asyncio reactor with "Task got bad yield: <Deferred>"
        # because a raw Twisted Deferred isn't asyncio-awaitable there.
        return deferToThread(self._fetch, request)

    def _fetch(self, request):
        headers = {
            k.decode("latin1"): b", ".join(v).decode("latin1")
            for k, v in request.headers.items()
        }
        cookies = dict(request.cookies) if isinstance(request.cookies, dict) else {}
        method = request.method or "GET"
        body = request.body if request.body else None

        resp = _SESSION.request(
            method,
            request.url,
            headers=headers,
            cookies=cookies,
            data=body,
            timeout=self.timeout,
            allow_redirects=True,
        )

        response_headers = [
            (k, v) for k, v in resp.headers.items()
            if k.lower() not in self._STRIP_RESPONSE_HEADERS
        ]
        return HtmlResponse(
            url=resp.url,
            body=resp.content,
            status=resp.status_code,
            headers=response_headers,
            request=request,
        )
