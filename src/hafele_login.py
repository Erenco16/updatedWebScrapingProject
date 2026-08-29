"""
src/hafele_login.py

Shared Selenium login used by:
  - hafele_harvester    (once, at pipeline start)
  - refresh_cookies.py  (every 10 min, sidecar keeps session alive)

Both write the resulting cookies to Redis at `hafele:session:cookies`.
"""
import json
import random
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from spiders.headers import CHROME_ARGUMENTS, CHROME_EXPERIMENTAL_OPTIONS

REDIS_COOKIES_KEY = "hafele:session:cookies"
REDIS_COOKIES_UA_KEY = "hafele:session:cookies:user_agent"
REDIS_COOKIES_TS_KEY = "hafele:session:cookies:refreshed_at"

# CDP stealth script: hides the automation fingerprints that survive plain
# ChromeOptions flags — `navigator.webdriver`, the empty plugins/languages
# arrays a bare ChromeDriver session reports, and the absent `window.chrome`
# object real Chrome always exposes. Injected before any page script runs,
# via Page.addScriptToEvaluateOnNewDocument, so it applies on every
# navigation for the life of the session (also present, with a JS syntax
# bug, in the unused spiders.middlewares.SeleniumGridMiddleware).
_STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-GB', 'en', 'tr']});
    window.chrome = { runtime: {} };
"""


def _driver(grid_url: str, user_agent: str):
    opts = Options()
    for arg in CHROME_ARGUMENTS:
        opts.add_argument(arg)
    opts.add_argument(f"--user-agent={user_agent}")
    for key, value in CHROME_EXPERIMENTAL_OPTIONS.items():
        opts.add_experimental_option(key, value)
    d = webdriver.Remote(command_executor=grid_url, options=opts)
    d.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument", {"source": _STEALTH_JS}
    )
    return d


def login_and_get_cookies(
    grid_url: str, user_agent: str, username: str, password: str
) -> tuple[dict, bool]:
    """Drive Selenium Grid through the Hafele login flow.

    Returns (cookies_dict, probe_logged_in). The probe is a real API call
    inside the browser — if the response contains `values-tr` or
    `availability-flag`, we know we are logged in.
    """
    d = _driver(grid_url, user_agent)
    try:
        time.sleep(random.uniform(2, 5))
        d.get("https://www.hafele.com.tr/tr/")
        time.sleep(5)

        # OneTrust cookie banner
        d.execute_script(
            "var b=document.getElementById('onetrust-accept-btn-handler');"
            " if(b) b.click();"
        )
        time.sleep(1)

        # Country modal → close (X) button. Distinct from the login modal's
        # own close button (class "closeButton" there vs "cancelButton"
        # here), so this selector can't accidentally fire on the wrong modal.
        d.execute_script(
            "var b=document.querySelector('button.close.cancelButton"
            "[data-dismiss=\"modal\"]'); if(b) b.click();"
        )
        time.sleep(2)

        # Open header login modal. The cookie-banner and country-modal clicks
        # above are guarded with `if(b) b.click()` because those elements may
        # legitimately not exist; this one used to be unguarded, so if
        # Cloudflare's JS challenge + page hydration took longer than the
        # fixed sleeps above, `getElementById` returned null and the raw
        # `.click()` crashed with "Cannot read properties of null (reading
        # 'click')". Wait for the element instead of assuming it's already
        # there.
        try:
            WebDriverWait(d, 20).until(
                EC.presence_of_element_located((By.ID, "headerLoginLinkAction"))
            )
        except TimeoutException:
            raise RuntimeError(
                "headerLoginLinkAction not found within 20s — page may still "
                "be on the Cloudflare challenge, or the header markup changed."
            )
        d.execute_script(
            "var b=document.getElementById('headerLoginLinkAction'); if(b) b.click();"
        )
        time.sleep(2)

        username_field = WebDriverWait(d, 15).until(
            EC.visibility_of_element_located((By.ID, "ShopLoginForm_Login_headerItemLogin"))
        )
        password_field = WebDriverWait(d, 15).until(
            EC.visibility_of_element_located((By.ID, "ShopLoginForm_Password_headerItemLogin"))
        )
        username_field.send_keys(username)
        password_field.send_keys(password)
        try:
            d.execute_script(
                "var b=document.getElementById('divShopLoginForm_RememberLogin_headerItemLogin');"
                " if(b) b.click();"
            )
        except Exception:
            pass
        time.sleep(1)

        try:
            WebDriverWait(d, 15).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'button[data-testid="ajaxAccountLoginFormBtn"]')
                )
            )
        except TimeoutException:
            raise RuntimeError(
                "ajaxAccountLoginFormBtn not clickable within 15s."
            )
        d.execute_script(
            "var b=document.querySelector('button[data-testid=\"ajaxAccountLoginFormBtn\"]');"
            " if(b) b.click();"
        )
        time.sleep(12)

        # In-browser probe: authenticated response is ~7 KB with values-tr rows.
        probe = d.execute_async_script(
            "var cb=arguments[arguments.length-1];"
            "fetch('/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/"
            "ViewProduct-GetPriceAndAvailabilityInformationPDS?SKU=82645712"
            "&ProductQuantity=20000&SynchronizationAjaxToken=1',"
            "{credentials:'include', headers:{'X-Requested-With':'XMLHttpRequest'}})"
            ".then(r=>r.text()).then(cb).catch(e=>cb('ERR:'+e));"
        )
        logged_in = "values-tr" in (probe or "") or "availability-flag" in (probe or "")

        cookies = d.get_cookies()
        cookie_dict = {
            c["name"]: c["value"]
            for c in cookies
            if c.get("name") and c.get("value") is not None
        }
        return cookie_dict, logged_in
    finally:
        try:
            d.quit()
        except Exception:
            pass


def save_cookies_to_redis(redis_client, cookies: dict, user_agent: str) -> None:
    """Persist cookies + UA + refreshed_at into Redis."""
    redis_client.set(REDIS_COOKIES_KEY, json.dumps(cookies))
    redis_client.set(REDIS_COOKIES_UA_KEY, user_agent)
    redis_client.set(REDIS_COOKIES_TS_KEY, str(int(time.time())))
