"""
HTTP headers constants for Häfele web scraper.

These headers match a real Chrome browser request to bypass Cloudflare anti-bot.
"""

# ─── Browser Identity ────────────────────────────────────────────

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)

SEC_CH_UA = (
    '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"'
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
