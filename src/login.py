from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import os
from dotenv import load_dotenv
import time
import pickle
import json

from src.util.logger_util import CustomLogger

log_manager = CustomLogger(__name__, log_file="login.log")
logger = log_manager.get_logger()

load_dotenv()

def handle_login(driver=None):
    """
    Handle login to Hafele website.
    
    If driver is passed, reuse it for login.
    If driver is None, create a new Remote driver and return it.
    """
    # Initialize Chrome options (needed regardless of whether driver is passed)
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    user_agent = os.getenv("USER_AGENT")
    if user_agent:
        options.add_argument(f"--user-agent={user_agent}")
    
    # If driver not passed, create a new one
    if driver is None:
        selenium_hub_url = os.getenv("GRID_URL", "http://selenium-hub:4444/wd/hub")
        driver = webdriver.Remote(
            command_executor=selenium_hub_url,
            options=options
        )

    # Open the website
    driver.get("https://www.hafele.com.tr/")
    time.sleep(5)

    # Get username and password from environment variables
    username = os.getenv("hafele_username")
    password = os.getenv("hafele_password")

    # Close the initial warning page
    try:
        element = driver.find_element(By.XPATH,
                                      "//a[contains(@class, 'a-btn') and contains(@class, 't-btn') and contains(@class, 't-btn-secondary') and contains(@class, 'modal-link')]")
        driver.execute_script("arguments[0].click();", element)
    except Exception as e:
        logger.exception(f"Warning page close failed: {e}")
        logger.exception(f"Warning page close failed: {e}")

    # Handle login
    login_header = driver.find_element(By.ID, "headerLoginLinkAction")
    login_header.click()

    username_input = driver.find_element(By.ID, "ShopLoginForm_Login_headerItemLogin")
    password_input = driver.find_element(By.ID, "ShopLoginForm_Password_headerItemLogin")
    username_input.send_keys(username)
    password_input.send_keys(password)

    # Keep session open checkbox
    try:
        checkbox = driver.find_element(By.ID, "divShopLoginForm_RememberLogin_headerItemLogin")
        checkbox.click()
    except Exception as e:
        logger.exception(f"Checkbox click failed: {e}")
        logger.exception(f"Checkbox click failed: {e}")

    time.sleep(2)

    # Login button click
    login_btn = driver.find_element(By.XPATH, "//button[@data-testid='ajaxAccountLoginFormBtn']")
    login_btn.click()
    time.sleep(10)

    # Define the absolute paths based on the current file's directory (i.e., the /src folder)
    base_path = os.path.dirname(__file__)
    cookie_file_path = os.path.join(base_path, "cookies.pkl")
    user_agent_file = os.path.join(base_path, "user_agent.txt")
    session_info_file = os.path.join(base_path, "session_info.json")

    # Save cookies after logging in
    try:
        with open(cookie_file_path, "wb") as file:
            logger.info(driver.get_cookies())
            logger.info(driver.get_cookies())
            pickle.dump(driver.get_cookies(), file)
        # Save the user agent
        with open(user_agent_file, "w") as file:
            file.write(options.arguments[-1].split("=")[-1])
    except Exception as e:
        logger.exception(f"Failed to save cookies: {e}")
        logger.exception(f"Failed to save cookies: {e}")

    # Save session information from localStorage
    try:
        session_info = driver.execute_script("return window.localStorage.getItem('sessionInfoData');")
        if session_info:
            # Parse and save sessionInfoData as JSON
            session_info_json = json.loads(session_info)
            with open(session_info_file, "w") as file:
                json.dump(session_info_json, file, indent=4)
                file.flush()  # Ensure the data is written to disk
                os.fsync(file.fileno())  # Force the OS to flush the file
    except Exception as e:
        logger.exception(f"Failed to save session info: {e}")
        logger.exception(f"Failed to save session info: {e}")
    
    return driver
