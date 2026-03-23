"""
page_loader.py
--------------
Responsible for:
- Waiting for pages to be in a readable state (replaces flat time.sleep)
- Detecting and backing off from Cloudflare challenge pages
"""

import time
import random
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from src.util.logger_util import CustomLogger

log_manager = CustomLogger(__name__, log_file="page_loader.log")
logger = log_manager.get_logger()

CLOUDFLARE_MARKERS = [
    "Just a moment",
    "Checking your browser",
    "cf-challenge",
    "Challenge Processing",
]


def wait_for_page_ready(driver, timeout=20):
    """
    Wait until document.readyState is 'complete'.
    Falls back gracefully if the wait times out.
    """
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except Exception:
        pass


def wait_for_element_or_error(driver, timeout=15):
    """
    Wait until either a known product element OR the 'not found' error paragraph
    appears in the DOM. Returns page source once something meaningful is present.

    Replaces flat time.sleep(2) after driver.get() calls.
    """
    try:
        WebDriverWait(driver, timeout).until(
            EC.any_of(
                EC.presence_of_element_located((By.CSS_SELECTOR, "span.price")),
                EC.presence_of_element_located((By.CSS_SELECTOR, "tr.values-tr")),
                EC.presence_of_element_located((By.CSS_SELECTOR, "p.headlineStyle4")),
                EC.presence_of_element_located((By.CSS_SELECTOR, "tr#productBomArticlesInformation")),
            )
        )
    except Exception:
        pass
    return driver.page_source


def is_cloudflare_challenge(page_source):
    """Return True if the page source looks like a Cloudflare challenge page."""
    lower = page_source.lower()
    return any(marker.lower() in lower for marker in CLOUDFLARE_MARKERS)


def detect_and_backoff_cloudflare(driver, max_backoff=60):
    """
    Check the current page for a Cloudflare challenge.
    If found: sleep, refresh, and wait for the page to recover.

    Returns True if a challenge was detected.
    """
    try:
        if not is_cloudflare_challenge(driver.page_source):
            return False

        backoff_time = random.uniform(20, min(60, max_backoff))
        logger.info(f"  ⚠ Cloudflare challenge detected! Backing off for {backoff_time:.1f}s...")
        time.sleep(backoff_time)

        try:
            driver.refresh()
            wait_for_page_ready(driver)
        except Exception as e:
            logger.exception(f"  ⚠ Refresh after Cloudflare backoff failed: {e}")

        return True

    except Exception as e:
        logger.exception(f"  ⚠ Error during Cloudflare detection: {e}")
        return False