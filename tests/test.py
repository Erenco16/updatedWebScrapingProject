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

# Add the parent directory to sys.path so we can import src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import main functions for testing
from src.main import (
    handle_singular_product,
    retrieve_product_data,
    extract_price_info,
    does_product_exist,
    extract_product_description
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


def fetch_product_page_with_headers(url, cookies):
    """Fetch the product page HTML with full headers matching browser request."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-GB,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1"
    }
    session = requests.Session()

    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'])

    try:
        response = session.get(url, headers=headers, timeout=60)
        if response.status_code == 200:
            print(f"✅ Product page fetched successfully from: {url}")
            return response.text
        else:
            print(f"❌ Failed to fetch product page. HTTP Status: {response.status_code}")
            return None
    except requests.RequestException as e:
        print(f"❌ Request error: {e}")
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


def test_extract_product_description(soup):
    """Test the `extract_product_description()` function."""
    print("\nTesting extract_product_description()...")
    try:
        result = extract_product_description(soup)
        if result and result != "No description available":
            # Check if it's valid HTML
            if "<!DOCTYPE html>" in result and "<html" in result:
                print("✅ Product description HTML generated successfully")
                print(f"   - HTML length: {len(result)} characters")
                # Check for key HTML elements
                if "product-description-container" in result:
                    print("   - Contains product-description-container")
                if "property-section" in result:
                    print("   - Contains property sections")
                if "Ürün Özellikleri" in result:
                    print("   - Contains Turkish header")
                print(f"   - First 200 chars: {result[:200]}...")
            else:
                print("⚠️ Result is not valid HTML")
                print(f"   Result: {result[:200]}...")
        else:
            print(f"⚠️ No description available: {result}")
    except Exception as e:
        print(f"Error in extract_product_description: {e}")
        import traceback
        traceback.print_exc()


def test_does_product_exist(code, cookies):
    """Test the `does_product_exist()` function."""
    print("\nTesting does_product_exist()...")
    try:
        exists, search_soup = does_product_exist(code=code, cookies=cookies)
        print(f"✅ Product exists: {exists}")
        
        # Print relevant information from the search results page
        if search_soup:
            print(f"\n📄 Search Results Page HTML Preview:")
            print(f"   - Page title: {search_soup.title.string if search_soup.title else 'N/A'}")
            
            # Look for product count or search results info
            search_info = search_soup.find("p", class_="headlineStyle4")
            if search_info:
                print(f"   - Search info: {search_info.get_text(strip=True)[:200]}...")
            
            # Check for products in search results
            products = search_soup.find_all("div", class_="productDataTableRow")
            print(f"   - Products found in results: {len(products)}")
            
            # Print first few products if available
            if products:
                print(f"   - First product: {products[0].get_text(strip=True)[:100]}...")
            
            # Print full HTML if product doesn't exist (for debugging)
            if not exists:
                print(f"\n   - Full search page HTML (first 1000 chars):\n{search_soup.prettify()[:1000]}")
        
        return exists, search_soup
    except Exception as e:
        print(f"Error in does_product_exist: {e}")
        import traceback
        traceback.print_exc()


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
    print(f"\nTesting product URL (API endpoint): {product_url}")

    # Step 3: Fetch product page from API endpoint
    print("\n=== Fetching from API endpoint ===")
    html = fetch_product_page(product_url, cookies)
    if not html:
        print("Failed to fetch product page from API endpoint.")
        html = None
    else:
        # Parse the HTML with BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # Step 4: Run individual function tests
        print("\n--- Running Function Tests (API Endpoint) ---")
        test_handle_singular_product(soup)
        test_extract_price_info(soup)
        test_extract_product_description(soup)
    
    # Now try fetching from the search/direct product URL
    print("\n\n=== Fetching from search endpoint ===")
    exists, search_soup = test_does_product_exist(code=product_code, cookies=cookies)
    
    if search_soup and exists:
        print("\n--- Running Function Tests (Search/Direct Product Page) ---")
        product_description_from_search = extract_product_description(search_soup)
        print("\n✅ Testing extract_product_description() with search page soup...")
        if product_description_from_search and product_description_from_search != "No description available":
            if "<!DOCTYPE html>" in product_description_from_search and "<html" in product_description_from_search:
                print("✅ Product description HTML generated successfully from search page")
                print(f"   - HTML length: {len(product_description_from_search)} characters")
                if "product-description-container" in product_description_from_search:
                    print("   - Contains product-description-container")
                if "property-section" in product_description_from_search:
                    print("   - Contains property sections")
            else:
                print("⚠️ Result is not valid HTML")
        else:
            print(f"⚠️ No description available from search page: {product_description_from_search}")
    
    # Test retrieve_product_data (which uses both URLs)
    print("\n\n--- Testing Full retrieve_product_data() ---")
    test_retrieve_product_data(url=product_url, cookies=cookies, code=product_code)


if __name__ == "__main__":
    main()
