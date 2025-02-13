import sys
import os
import pickle
import json
import time
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

# Load environment variables
load_dotenv()

# Add the src directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

# Import main functions for testing
from src.main import (
    handle_singular_product,
    retrieve_product_data,
    extract_price_info,
    does_product_exist
)

# Constants
COOKIE_FILE = "cookies.pkl"
BASE_PRODUCT_URL = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"


def handle_login():
    """Perform login using Selenium and save cookies."""
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.add_argument("--headless")  # Run headless
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"user-agent={os.getenv('USER_AGENT', 'Mozilla/5.0')}")

    driver = webdriver.Chrome(options=options)

    driver.get("https://www.hafele.com.tr/")
    time.sleep(5)

    username = os.getenv("hafele_username")
    password = os.getenv("hafele_password")

    try:
        element = driver.find_element(By.XPATH, "//a[contains(@class, 'a-btn') and contains(@class, 'modal-link')]")
        driver.execute_script("arguments[0].click();", element)
    except Exception:
        pass  # If the warning page doesn't appear, continue

    # Handle login
    login_header = driver.find_element(By.ID, "headerLoginLinkAction")
    login_header.click()

    username_input = driver.find_element(By.ID, "ShopLoginForm_Login_headerItemLogin")
    password_input = driver.find_element(By.ID, "ShopLoginForm_Password_headerItemLogin")
    username_input.send_keys(username)
    password_input.send_keys(password)

    try:
        checkbox = driver.find_element(By.ID, "divShopLoginForm_RememberLogin_headerItemLogin")
        checkbox.click()
    except Exception:
        pass  # Ignore checkbox error if not present

    time.sleep(2)

    login_btn = driver.find_element(By.XPATH, "//button[@data-testid='ajaxAccountLoginFormBtn']")
    login_btn.click()
    time.sleep(10)

    # Save cookies
    with open(COOKIE_FILE, "wb") as file:
        pickle.dump(driver.get_cookies(), file)

    # Save session information
    try:
        session_info = driver.execute_script("return window.localStorage.getItem('sessionInfoData');")
        if session_info:
            session_info_json = json.loads(session_info)
            with open("session_info.json", "w") as file:
                json.dump(session_info_json, file, indent=4)
            print(f"Session info saved: {session_info_json}")
    except Exception:
        pass  # Ignore session info error if not present

    driver.quit()


def load_cookies():
    """Load cookies from file or perform login if missing."""
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, "rb") as file:
            return pickle.load(file)
    else:
        print("No existing cookies found. Logging in...")
        handle_login()
        with open(COOKIE_FILE, "rb") as file:
            return pickle.load(file)


def fetch_product_page(url, cookies):
    """Fetch the product page HTML using the provided cookies."""
    headers = {"User-Agent": "Mozilla/5.0"}
    session = requests.Session()

    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'])

    try:
        response = session.get(url, headers=headers, timeout=60)
        if response.status_code == 200:
            print("Product page fetched successfully.")
            return response.text
        else:
            print(f"Failed to fetch product page. HTTP Status: {response.status_code}")
            return None
    except requests.RequestException as e:
        print(f"Request error: {e}")
        return None


def test_handle_singular_product(soup):
    """Test the `handle_singular_product()` function."""
    print("\nTesting handle_singular_product()...")
    try:
        result = handle_singular_product(soup)
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error in handle_singular_product: {e}")


def test_extract_price_info(soup):
    """Test the `extract_price_info()` function."""
    print("\nTesting extract_price_info()...")
    try:
        result = extract_price_info(soup)
        print(f"Prices extracted: {result}")
    except Exception as e:
        print(f"Error in extract_price_info: {e}")


def test_does_product_exist(code, cookies):
    """Test the `does_product_exist()` function."""
    print("\nTesting does_product_exist()...")
    try:
        result = does_product_exist(code=code, cookies=cookies)
        print(f"Product exists: {result}")
    except Exception as e:
        print(f"Error in does_product_exist: {e}")


def test_retrieve_product_data(url, code, cookies):
    """Test the `retrieve_product_data()` function."""
    print("\nTesting retrieve_product_data()...")
    try:
        result = retrieve_product_data(url=url, code=code, cookies=cookies)
        print(f"Product data: {result}")
    except Exception as e:
        print(f"Error in retrieve_product_data: {e}")


def main():
    # Step 1: Load cookies or perform login
    cookies = load_cookies()
    if not cookies:
        print("Unable to load cookies. Exiting tests.")
        return

    # Step 2: Provide product code
    product_code = input("Enter product code to test (e.g., 806.68.713): ").strip()
    product_url = f"{BASE_PRODUCT_URL}?SKU={product_code.replace('.', '')}&ProductQuantity=20000"
    print(f"\nTesting product URL: {product_url}")

    # Step 3: Fetch product page
    html = fetch_product_page(product_url, cookies)
    if not html:
        print("Failed to fetch product page. Exiting tests.")
        return

    # Parse the HTML with BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # Step 4: Run individual function tests
    print("\n--- Running Function Tests ---")
    test_handle_singular_product(soup)
    test_extract_price_info(soup)
    test_does_product_exist(code=product_code, cookies=cookies)
    test_retrieve_product_data(url=product_url, cookies=cookies, code=product_code)


if __name__ == "__main__":
    main()
