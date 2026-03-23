# src/selenium_client.py
import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from src.util.logger_util import CustomLogger

log_manager = CustomLogger(__name__, log_file="selenium-client.log")
logger = log_manager.get_logger()

def make_driver(retries=10, retry_delay=2):
    """
    Create a Selenium WebDriver connected to Selenium Grid with robust retry logic.
    
    Args:
        retries: Number of times to retry driver creation if it fails
        retry_delay: Delay in seconds between retries
    
    Returns:
        WebDriver instance connected to Selenium Grid
    
    Raises:
        RuntimeError: If unable to create driver after all retries
    """
    grid_url = os.getenv("GRID_URL")
    if not grid_url:
        raise RuntimeError("GRID_URL is not set. In Docker it should be like http://selenium-hub:4444/wd/hub")

    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--headless=new")  # better for modern chrome
    
    ua = os.getenv("USER_AGENT")
    if ua:
        options.add_argument(f"--user-agent={ua}")

    # Retry loop to handle Grid startup race conditions
    for attempt in range(retries):
        try:
            logger.info(f"Attempting to create Selenium driver (attempt {attempt + 1}/{retries})...")
            driver = webdriver.Remote(command_executor=grid_url, options=options)
            logger.info(f"✅ Successfully created Selenium driver")
            return driver
        except Exception as e:
            logger.exception(f"❌ Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                logger.info(f"⏳ Waiting {retry_delay}s before retry...")
                time.sleep(retry_delay)
            else:
                raise RuntimeError(
                    f"Failed to create Selenium driver after {retries} retries. "
                    f"Last error: {e}"
                )

