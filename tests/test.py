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
    retrieve_qty_available,
    extract_price_info,
    does_product_exist
)

# Constants
COOKIE_FILE = "cookies.pkl"
BASE_PRODUCT_URL = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"


def handle_login():
    """Perform login using regular Selenium (not Selenium Grid)."""
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.add_argument("--headless")  # Run headless
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"user-agent={os.getenv('USER_AGENT', 'Mozilla/5.0')}")

    # Use regular Selenium for local execution
    driver = webdriver.Chrome(options=options)

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
        print(f"Warning page close failed: {e}")

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
        print(f"Checkbox click failed: {e}")

    time.sleep(2)

    # Login button click
    login_btn = driver.find_element(By.XPATH, "//button[@data-testid='ajaxAccountLoginFormBtn']")
    login_btn.click()
    time.sleep(10)

    # Save cookies after logging in
    try:
        with open(COOKIE_FILE, "wb") as file:
            pickle.dump(driver.get_cookies(), file)
        with open("user_agent.txt", "w") as file:
            file.write(options.arguments[-1].split("=")[-1])
    except Exception as e:
        print(f"Failed to save cookies: {e}")

    # Save session information from localStorage
    try:
        session_info = driver.execute_script("return window.localStorage.getItem('sessionInfoData');")
        if session_info:
            session_info_json = json.loads(session_info)
            with open("session_info.json", "w") as file:
                json.dump(session_info_json, file, indent=4)
            print(f"Session info saved: {session_info_json}")
        else:
            print("No sessionInfoData found in localStorage.")
    except Exception as e:
        print(f"Failed to save session info: {e}")

    return driver


def load_cookies():
    """Load cookies from the cookies file if they exist."""
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, "rb") as file:
            cookies = pickle.load(file)
        print("Cookies loaded.")
        return {cookie["name"]: cookie["value"] for cookie in cookies}
    else:
        print("Cookies not found. Logging in...")
        handle_login()  # Login before proceeding
        return load_cookies()


def fetch_product_page(url, cookies):
    """Fetch the product page HTML using the provided cookies."""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=60)
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


def test_does_product_exist(soup):
    """Test the `does_product_exist()` function."""
    print("\nTesting does_product_exist()...")
    try:
        result = does_product_exist(soup)
        print(f"Product exists: {result}")
    except Exception as e:
        print(f"Error in does_product_exist: {e}")


def test_retrieve_qty_available(url, cookies):
    """Test the `retrieve_qty_available()` function."""
    print("\nTesting retrieve_qty_available()...")
    try:
        qty = retrieve_qty_available(url, cookies)
        print(f"Quantity available: {qty}")
    except Exception as e:
        print(f"Error in retrieve_qty_available: {e}")


def test_retrieve_product_data(url, cookies):
    """Test the `retrieve_product_data()` function."""
    print("\nTesting retrieve_product_data()...")
    try:
        result = retrieve_product_data(url, cookies)
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
    product_url = f"{BASE_PRODUCT_URL}?SKU={product_code.replace('.', '')}&ProductQuantity=50000"
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
    test_does_product_exist(soup)
    test_retrieve_qty_available(product_url, cookies)
    test_retrieve_product_data(product_url, cookies)


if __name__ == "__main__":
    main()
