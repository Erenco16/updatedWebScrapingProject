"""Custom Scrapy middlewares.

- RedisCookieMiddleware: pulls fresh session cookies from Redis on a short
  TTL and attaches them to every request. Pairs with the cookie-refresher
  sidecar so long-running processors don't drift onto expired sessions.
- ScraplingDownloadMiddleware: fetch via Scrapling's Fetcher in a worker
  thread instead of Twisted's built-in HTTP client. Cloudflare fingerprints
  and blocks Twisted's TLS/connection stack on hafele.com.tr even with
  byte-identical cookies/headers that pass fine through any ordinary HTTP
  client. Scrapling's Fetcher (httpx-based) sits in exactly that "ordinary"
  bucket, so swapping it in resolves the 403s without touching the rest of
  Scrapy's pipeline (RetryMiddleware, item pipeline, spider callbacks).

  Rule 3 of the project's framework spec says to escalate to StealthyFetcher
  if a target BLOCKS traditional clients. Hafele doesn't block us — once
  the session is authenticated (cookies in Redis via the Selenium login),
  the lightweight Fetcher gets 200s. If Cloudflare ever tightens its edge
  rules and starts rejecting the httpx fingerprint too, swap
  ``_FETCHER_CLS`` below for ``StealthyFetcher`` (adds a Playwright browser
  per thread — much heavier, so default off).

- SeleniumGridMiddleware: legacy JS-render fallback (currently unused,
  kept for the rare case where a page needs full JS execution and
  StealthyFetcher's Playwright isn't enough).
"""
import json
import os
import time
import random
import redis
import socket

from scrapy.http import HtmlResponse
from scrapy import signals
from twisted.internet.threads import deferToThread

# Force IPv4 globally for every socket-using library in the process.
# The Docker network on this host only routes IPv4 outbound reliably;
# DNS can return AAAA records for hafele.com.tr and libraries that
# prefer IPv6 then fail immediately with "Network is unreachable",
# especially during the first seconds after a container starts.
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_only_getaddrinfo(host, port, *args, **kwargs):
    try:
        results = _orig_getaddrinfo(host, port, *args, **kwargs)
    except Exception:
        raise
    v4 = [r for r in results if r[0] == socket.AF_INET]
    return v4 or results


socket.getaddrinfo = _ipv4_only_getaddrinfo

# Scrapling's Fetcher is the project-mandated replacement for raw requests.
# Imported after the IPv4 patch so its httpx client inherits the socket
# behaviour. Kept behind a module-level alias so the escalation path to
# StealthyFetcher is a one-line change.
import random  # noqa: E402

from scrapling.fetchers import Fetcher  # noqa: E402

_FETCHER_CLS = Fetcher

# curl_cffi-backed browser impersonation profiles for Scrapling. We pick
# one at random per request so TLS/UA fingerprints vary across the queue
# and don't collapse to a single easily-blocked signature.
from spiders.headers import IMPERSONATION_PROFILES  # noqa: E402


def _pick_impersonation_profile() -> str:
    """Return one of the Scrapling-supported browser aliases.

    Kept as a module-level function (not just inlined ``random.choice``)
    so tests can patch it deterministically and so a future upgrade to a
    weighted / sticky-per-session strategy only needs one edit site.
    """
    return random.choice(IMPERSONATION_PROFILES)

from selenium import webdriver  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402
from selenium.webdriver.support.ui import WebDriverWait  # noqa: E402
from selenium.webdriver.support import expected_conditions as EC  # noqa: E402
from selenium.webdriver.chrome.options import Options as ChromeOptions  # noqa: E402

from spiders.headers import CHROME_ARGUMENTS, CHROME_EXPERIMENTAL_OPTIONS, USER_AGENT  # noqa: E402

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
    """Attach fresh session cookies from Redis to every outgoing request
    whose host is hafele.com.tr.

    Reads `hafele:session:cookies` (JSON), caches the result in-process for
    `COOKIE_CACHE_TTL` seconds (default 60), and sets `request.cookies` so
    the downstream fetch middleware serialises them into the Cookie header.

    Only Hafele hosts receive the cookies: downstream helper calls (e.g.
    the Dinler stock-fallback API) must not leak Hafele session tokens to
    unrelated third parties.

    Pair with the `cookie-refresher` sidecar, which re-logs in every 10 min
    and updates the same Redis key. Processors then automatically pick up
    the new cookies within one TTL window without needing to restart.
    """

    _HAFELE_HOST_SUFFIX = "hafele.com.tr"

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
        # Skip cookie injection for non-Hafele hosts (e.g. the Dinler
        # fallback API). Hafele's session cookies have no meaning there
        # and leaking them is both pointless and bad hygiene.
        from urllib.parse import urlparse
        host = (urlparse(request.url).hostname or "").lower()
        if not host.endswith(self._HAFELE_HOST_SUFFIX):
            return None
        # Merge — request-level cookies (rarely used here) take priority.
        current = dict(request.cookies) if isinstance(request.cookies, dict) else {}
        merged = dict(self._cookies)
        merged.update(current)
        request.cookies = merged
        return None


# ─── Scrapling-based download middleware ─────────────────────────

class ScraplingDownloadMiddleware:
    """Fetch every request via Scrapling's Fetcher in a worker thread.

    Scrapling is the project's mandated HTTP/parsing framework (no raw
    requests, no raw BeautifulSoup). Running it in a thread via
    ``deferToThread`` keeps Scrapy's Twisted reactor unblocked while the
    sync Fetcher call does its work.

    Register at a priority AFTER RedisCookieMiddleware (100) — e.g. 150 —
    so cookies are already merged onto ``request.cookies`` before we
    fetch, and so Scrapy's built-in CookiesMiddleware (700) is
    short-circuited (returning a Response from process_request stops the
    chain and prevents it from fighting the Redis-sourced cookie jar).
    """

    # Response headers the Fetcher has already consumed on our behalf
    # (body is already decompressed, so passing Content-Encoding through
    # would make HttpCompressionMiddleware try to gunzip plain bytes).
    _STRIP_RESPONSE_HEADERS = {"content-encoding", "content-length", "transfer-encoding"}

    # Transient transport failures we retry inside one Scrapy attempt so a
    # brief network blip at container startup doesn't surface as a
    # permanent failure to the spider's errback.
    _RETRY_BACKOFFS = (0.0, 1.0, 2.0, 4.0, 8.0)

    def __init__(self, timeout: float):
        self.timeout = timeout

    @classmethod
    def from_crawler(cls, crawler):
        return cls(timeout=crawler.settings.getfloat("DOWNLOAD_TIMEOUT", 60))

    def process_request(self, request, spider):
        # Returning a Deferred is soft-deprecated but still supported; the
        # `async def` variant fails under Scrapy's asyncio reactor with
        # "Task got bad yield: <Deferred>" because a raw Twisted Deferred
        # isn't asyncio-awaitable in that context.
        return deferToThread(self._fetch, request)

    def _decode_headers(self, request) -> dict:
        return {
            k.decode("latin1"): b", ".join(v).decode("latin1")
            for k, v in request.headers.items()
        }

    def _fetch(self, request):
        headers = self._decode_headers(request)
        cookies = dict(request.cookies) if isinstance(request.cookies, dict) else {}
        method = (request.method or "GET").upper()

        last_err: Exception | None = None
        for backoff in self._RETRY_BACKOFFS:
            if backoff:
                time.sleep(backoff)
            try:
                return self._do_one_fetch(method, request, headers, cookies)
            except Exception as e:
                # Only transport-level failures get retried; a successful
                # fetch with a 4xx/5xx is still a "success" at this layer
                # and Scrapy's RetryMiddleware handles those.
                last_err = e
        raise last_err  # exhausted retries -> errback fires in the spider

    def _do_one_fetch(self, method: str, request, headers: dict, cookies: dict):
        fetch_fn = getattr(_FETCHER_CLS, method.lower(), None)
        if fetch_fn is None:
            fetch_fn = _FETCHER_CLS.get

        # Scrapling's curl_cffi-backed impersonation mints a matching
        # browser UA + Client Hints + TLS fingerprint and overrides any
        # UA already in `headers` at the wire layer. One profile per
        # request keeps the fingerprint-rotation surface wide.
        #
        # ``request.meta['impersonate_override']`` lets a spider pin a
        # specific profile on retry — used by the Dinler-block-page
        # retry path to force rotating off the profile that tripped
        # Cloudflare's TDM block on the previous attempt.
        impersonate = request.meta.get("impersonate_override") or _pick_impersonation_profile()
        # Record which profile actually went on the wire so a retry
        # callback can pick a *different* one next time.
        request.meta["impersonate_used"] = impersonate

        kwargs = dict(
            headers=headers,
            cookies=cookies,
            timeout=self.timeout,
            follow_redirects=True,
            impersonate=impersonate,
        )
        # Scrapling's various fetcher versions differ in which kwargs
        # they accept; strip ones that aren't understood rather than
        # crashing the whole call. Scrapling >= 0.3 renamed
        # ``follow_redirects`` to ``allow_redirects``.
        try:
            resp = fetch_fn(request.url, **kwargs)
        except TypeError:
            kwargs.pop("follow_redirects", None)
            try:
                resp = fetch_fn(request.url, **kwargs, allow_redirects=True)
            except TypeError:
                # Last-ditch: strip impersonate too in case a future
                # Scrapling drops the kwarg name.
                kwargs.pop("impersonate", None)
                resp = fetch_fn(request.url, **kwargs)

        return self._wrap_response(resp, request)

    def _wrap_response(self, resp, request):
        # Scrapling's Response exposes the same conceptual fields as
        # requests.Response but under slightly different attribute names
        # across versions. Pull defensively.
        body = (
            getattr(resp, "content", None)
            or getattr(resp, "body", None)
            or (resp.text.encode("utf-8") if getattr(resp, "text", None) else b"")
        )
        if isinstance(body, str):
            body = body.encode("utf-8")

        status = (
            getattr(resp, "status_code", None)
            or getattr(resp, "status", None)
            or 200
        )
        resp_url = getattr(resp, "url", request.url) or request.url
        raw_headers = getattr(resp, "headers", {}) or {}
        try:
            headers_iter = raw_headers.items()
        except AttributeError:
            headers_iter = list(raw_headers)

        response_headers = [
            (k, v) for k, v in headers_iter
            if str(k).lower() not in self._STRIP_RESPONSE_HEADERS
        ]
        return HtmlResponse(
            url=resp_url,
            body=body,
            status=status,
            headers=response_headers,
            request=request,
        )


# Backwards-compat alias: existing docker-compose logs and any external
# references to the old class name still resolve. New code should use
# ``ScraplingDownloadMiddleware`` directly.
RequestsDownloadMiddleware = ScraplingDownloadMiddleware
