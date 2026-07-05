"""
src/hafele_login.py

Shared Selenium login used by:
  - hafele_harvester    (once, at pipeline start)
  - refresh_cookies.py  (every 10 min, sidecar keeps session alive)

Both write the resulting cookies to Redis at `hafele:session:cookies`.
"""
import json
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

REDIS_COOKIES_KEY = "hafele:session:cookies"
REDIS_COOKIES_UA_KEY = "hafele:session:cookies:user_agent"
REDIS_COOKIES_TS_KEY = "hafele:session:cookies:refreshed_at"


def _driver(grid_url: str, user_agent: str):
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(f"--user-agent={user_agent}")
    return webdriver.Remote(command_executor=grid_url, options=opts)


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
        d.get("https://www.hafele.com.tr/")
        time.sleep(5)

        # OneTrust cookie banner
        d.execute_script(
            "var b=document.getElementById('onetrust-accept-btn-handler');"
            " if(b) b.click();"
        )
        time.sleep(1)

        # Country modal → "Stay Here" (secondary button)
        d.execute_script(
            "var b=document.querySelector('a.modal-link.t-btn-secondary,"
            "button.modal-link.t-btn-secondary'); if(b) b.click();"
        )
        time.sleep(2)

        # Open header login modal
        d.execute_script("document.getElementById('headerLoginLinkAction').click();")
        time.sleep(2)

        d.find_element(By.ID, "ShopLoginForm_Login_headerItemLogin").send_keys(username)
        d.find_element(By.ID, "ShopLoginForm_Password_headerItemLogin").send_keys(password)
        try:
            d.execute_script(
                "var b=document.getElementById('divShopLoginForm_RememberLogin_headerItemLogin');"
                " if(b) b.click();"
            )
        except Exception:
            pass
        time.sleep(1)

        d.execute_script(
            "document.querySelector('button[data-testid=\"ajaxAccountLoginFormBtn\"]').click();"
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
