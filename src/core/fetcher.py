import os
import time
from typing import List
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def create_session_from_cookies(cookies: List[dict]) -> requests.Session:
    """Creates a requests.Session with Selenium cookies."""
    session = requests.Session()
    for cookie in cookies:
        try:
            session.cookies.set(cookie["name"], cookie["value"])
        except Exception as e:
            print(f"⚠️ Skipping malformed cookie: {cookie} - Reason: {e}")

    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-GB,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1"
    })
    return session


def fetch_product_page_selenium(url: str, cookies: List[dict]) -> str:
    """
    Load the product page using Selenium and inject cookies properly.
    """
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Remote(
        command_executor=os.getenv("GRID_URL", "http://selenium-hub:4444/wd/hub"),
        options=options
    )

    try:
        # Navigate to domain to allow cookie injection
        driver.get("https://www.hafele.com.tr/")
        time.sleep(2)

        for cookie in cookies:
            try:
                name = cookie.get("name")
                value = cookie.get("value")

                # Skip malformed or empty cookies
                if not name or not value:
                    continue

                sanitized_cookie = {
                    "name": name,
                    "value": value,
                    "path": "/",
                    "secure": True
                }

                # Don't set domain for __Host- cookies (they must be host-only)
                if not name.startswith("__Host-"):
                    sanitized_cookie["domain"] = ".hafele.com.tr"

                driver.add_cookie(sanitized_cookie)

            except Exception as e:
                print(f"⚠️ Cookie error [{cookie.get('name')}]: {e}")

        # Navigate to target page with cookies set
        driver.get(url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#productPriceInformation"))
        )

        return driver.page_source
    finally:
        driver.quit()
