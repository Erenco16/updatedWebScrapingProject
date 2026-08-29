"""
src/hafele_login.py

Shared login used by:
  - hafele_harvester    (once, at pipeline start)
  - refresh_cookies.py  (every 10 min, sidecar keeps session alive)

Both write the resulting cookies to Redis at `hafele:session:cookies`.

Drives a *local* SeleniumBase UC-mode Chromium (not the selenium-hub Grid).
Plain Selenium/Selenium Grid keeps an always-on CDP/DevTools connection to
issue every command, and Cloudflare's Turnstile challenge on this site
detects that connection itself -- no ChromeOptions flag or JS property
patch (hiding navigator.webdriver, spoofing plugins/languages, faking
window.chrome) gets past it, confirmed by testing all of them directly.
SeleniumBase's `uc_open_with_reconnect` works around this by briefly
disconnecting the CDP session around the initial navigation, which is the
documented working technique against Turnstile's "non-interactive" managed
challenge. This needs a real (non-headless) browser via Xvfb -- headless
UC mode is markedly less reliable -- and briefly runs two Chromium
processes back to back (the old one shutting down, the new one starting),
so the host needs enough headroom for that overlap.
"""
import json
import random
import signal
import time
from contextlib import suppress

from sbvirtualdisplay import Display
from seleniumbase import Driver
from seleniumbase.core.browser_launcher import uc_open_with_reconnect
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

REDIS_COOKIES_KEY = "hafele:session:cookies"
REDIS_COOKIES_UA_KEY = "hafele:session:cookies:user_agent"
REDIS_COOKIES_TS_KEY = "hafele:session:cookies:refreshed_at"

LOGIN_TIMEOUT_SECONDS = 90


class LoginTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise LoginTimeout(
        f"Login flow exceeded {LOGIN_TIMEOUT_SECONDS}s "
        "(Chromium relaunch during uc_open_with_reconnect can stall if the "
        "host is short on memory)."
    )


def login_and_get_cookies(
    grid_url: str, user_agent: str, username: str, password: str
) -> tuple[dict, bool]:
    """Drive a local UC-mode Chromium through the Hafele login flow.

    `grid_url` is accepted for call-site compatibility but unused -- see
    the module docstring for why this no longer talks to selenium-hub.

    Returns (cookies_dict, probe_logged_in). The probe is a real API call
    inside the browser — if the response contains `values-tr` or
    `availability-flag`, we know we are logged in.
    """
    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(LOGIN_TIMEOUT_SECONDS)
    display = Display(visible=False, size=(1280, 800), backend="xvfb")
    display.start()
    d = None
    try:
        # No `agent=` override: forcing a UA string that doesn't match the
        # real installed Chromium build creates exactly the UA/Client-Hints
        # inconsistency Cloudflare Turnstile flags (confirmed by testing --
        # every attempt with a spoofed UA failed to clear the challenge,
        # every attempt using Chromium's own genuine UA passed).
        d = Driver(
            uc=True,
            headed=True,
            binary_location="/usr/bin/chromium",
            window_size="1280,800",
            no_sandbox=True,
        )
        time.sleep(random.uniform(2, 5))
        uc_open_with_reconnect(d, "https://www.hafele.com.tr/tr/", reconnect_time=6)
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
        # legitimately not exist; wait for this one instead of assuming it's
        # already there.
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
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
        if d is not None:
            with suppress(Exception):
                d.quit()
        with suppress(Exception):
            display.stop()


def save_cookies_to_redis(redis_client, cookies: dict, user_agent: str) -> None:
    """Persist cookies + UA + refreshed_at into Redis."""
    redis_client.set(REDIS_COOKIES_KEY, json.dumps(cookies))
    redis_client.set(REDIS_COOKIES_UA_KEY, user_agent)
    redis_client.set(REDIS_COOKIES_TS_KEY, str(int(time.time())))
