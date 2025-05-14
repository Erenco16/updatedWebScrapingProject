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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


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
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"user-agent={os.getenv('USER_AGENT', 'Mozilla/5.0')}")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 15)

    driver.get("https://www.hafele.com.tr/")
    time.sleep(3)

    username = os.getenv("hafele_username")
    password = os.getenv("hafele_password")

    try:
        # Step 1: Click the accept button (if it's there)
        cookie_btn = wait.until(EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler")))
        driver.save_screenshot("onetrust-accept-btn-handler.png")
        cookie_btn.click()
        print("Cookie consent accepted.")

        # Step 2: Wait for the dark overlay to disappear (invisible or detached from DOM)
        wait.until(EC.invisibility_of_element_located((By.CLASS_NAME, "onetrust-pc-dark-filter")))
        print("Overlay disappeared normally.")
    except TimeoutException:
        driver.save_screenshot("not-found.png")
        print("Timeout waiting for overlay to disappear — trying to force-hide it with JS.")
        try:
            driver.execute_script("""
                let overlay = document.querySelector('.onetrust-pc-dark-filter');
                if (overlay) {
                    overlay.style.display = 'none';
                    overlay.remove();  // try to fully remove it
                }
            """)
            print("Overlay force-hidden with JavaScript.")
        except Exception as e:
            print(f"Failed to remove overlay manually: {e}")
    except Exception as e:
        print(f"Cookie banner handling failed or not present: {e}")

    # Step 2: Close initial modal if "Stay Here" is visible
    try:
        stay_here_btn = wait.until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//a[contains(@class, 'modal-link') and normalize-space(text())='Stay Here']"
            ))
        )
        driver.save_screenshot("initialmodel-open.png")
        driver.execute_script("arguments[0].click();", stay_here_btn)
        print("Clicked 'Stay Here' on initial modal.")
        time.sleep(1)
        driver.save_screenshot("initialmodel-closed.png")
    except Exception as e:
        print(f"No 'Stay Here' modal found or already handled: {e}")

    # Step 3: Click on the login button in header
    login_header = wait.until(EC.element_to_be_clickable((By.ID, "headerLoginLinkAction")))
    driver.execute_script("arguments[0].click();", login_header)

    # Step 4: Fill in login form
    username_input = wait.until(EC.visibility_of_element_located((By.ID, "ShopLoginForm_Login_headerItemLogin")))
    password_input = wait.until(EC.visibility_of_element_located((By.ID, "ShopLoginForm_Password_headerItemLogin")))
    username_input.send_keys(username)
    password_input.send_keys(password)

    # Step 5: Click 'Remember Me' checkbox (if found)
    try:
        checkbox = driver.find_element(By.ID, "divShopLoginForm_RememberLogin_headerItemLogin")
        checkbox.click()
    except Exception:
        pass

    # Final check for cookie accept button before login click
    try:
        final_cookie_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
        )
        final_cookie_btn.click()
        print("Accepted final cookie prompt.")
        # Wait for overlay to vanish again if needed
        WebDriverWait(driver, 5).until(
            EC.invisibility_of_element_located((By.CLASS_NAME, "onetrust-pc-dark-filter"))
        )
        print("Overlay cleared again.")
    except Exception as e:
        print("No final cookie prompt appeared.")

    # Always try to remove OneTrust overlay, just in case it's still present
    try:
        driver.execute_script("""
            let overlay = document.querySelector('.onetrust-pc-dark-filter');
            if (overlay) {
                overlay.style.display = 'none';
                overlay.style.visibility = 'hidden';
                overlay.style.pointerEvents = 'none';
                overlay.remove();
                console.log('OneTrust overlay force-removed.');
            }
        """)
        print("Overlay force-hidden before login click.")
        driver.save_screenshot("overlay-force-hidden.png")
    except Exception as e:
        print(f"Overlay removal (final attempt) failed: {e}")

    # Step 6: Submit the login form
    login_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='ajaxAccountLoginFormBtn']")))
    login_btn.click()

    time.sleep(10)

    driver.save_screenshot("after-login-click.png")

    # Step 7: Save cookies to file
    with open("cookies.pkl", "wb") as file:
        pickle.dump(driver.get_cookies(), file)

    # Step 8: Save sessionInfoData from localStorage (if exists)
    try:
        session_info = driver.execute_script("return window.localStorage.getItem('sessionInfoData');")
        if session_info:
            session_info_json = json.loads(session_info)
            with open("session_info.json", "w") as file:
                json.dump(session_info_json, file, indent=4)
            print("Session info saved.")
    except Exception as e:
        print(f"Session info not found or failed to save: {e}")

    driver.quit()


def load_cookies():
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
        result = retrieve_product_data(url=url, code=code, cookie_information=cookies)
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
