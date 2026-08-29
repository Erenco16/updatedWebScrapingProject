"""
HTTP headers constants for Häfele web scraper.

These headers match a real Chrome browser request to bypass Cloudflare anti-bot.
"""

# ─── Browser Identity ────────────────────────────────────────────

# These must match the *actual* browser installed in Dockerfile.harvester
# (plain Chromium via apt, unpinned -- currently 151) that mints
# cf_clearance, not an arbitrary version number. A UA/Client-Hints identity
# that doesn't match the browser which actually solved the Cloudflare
# challenge gets the replayed cf_clearance cookie rejected with a 403,
# even though the cookie itself is valid and fresh -- confirmed by testing:
# this exact mismatch (stale "Google Chrome 143" here vs the real
# unbranded Chromium 151 that logs in) is what broke the sitemap/price-API
# fetches. Re-check with `chromium --version` if this drifts again.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

# No "Google Chrome" brand: Dockerfile.harvester installs plain Chromium
# (apt package `chromium`), not Google's branded build, and Chromium's own
# navigator.userAgentData.brands never includes a "Google Chrome" entry.
SEC_CH_UA = (
    '"Chromium";v="151", "Not=A?Brand";v="99"'
)

SEC_CH_UA_MOBILE = "?0"

SEC_CH_UA_PLATFORM = '"Linux"'


# ─── Request Headers ─────────────────────────────────────────────

BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-GB,en;q=0.9,az-AZ;q=0.8,az;q=0.7,en-US;q=0.6,tr;q=0.5",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Sec-Ch-Ua": SEC_CH_UA,
    "Sec-Ch-Ua-Mobile": SEC_CH_UA_MOBILE,
    "Sec-Ch-Ua-Platform": SEC_CH_UA_PLATFORM,
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Priority": "u=0, i",
    "Referer": "https://www.hafele.com.tr/tr/",
}


# ─── API Headers (slightly different for XHR/fetch) ──────────────

API_HEADERS = {
    **BROWSER_HEADERS,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "*/*;q=0.8"
    ),
    "X-Requested-With": "XMLHttpRequest",
}


# ─── Selenium / Chrome Options ───────────────────────────────────

CHROME_ARGUMENTS = [
    "--headless=new",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--window-size=1920,1080",
    "--disable-blink-features=AutomationControlled",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-breakpad",
    "--disable-client-side-phishing-detection",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-features=TranslateUI",
    "--disable-hang-monitor",
    "--disable-ipc-flooding-protection",
    "--disable-popup-blocking",
    "--disable-prompt-on-repost",
    "--disable-renderer-backgrounding",
    "--force-color-profile=srgb",
    "--metrics-recording-only",
    "--no-first-run",
    "--safebrowsing-disable-auto-update",
    "--password-store=basic",
    "--use-mock-keychain",
]

CHROME_EXPERIMENTAL_OPTIONS = {
    "excludeSwitches": ["enable-automation"],
    "useAutomationExtension": False,
}
