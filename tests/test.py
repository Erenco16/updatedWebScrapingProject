import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pickle
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import time

# Add the root directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Add the src directory to sys.path to resolve imports from src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

# Add the src directory to sys.path to resolve imports from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

# Load environment variables
load_dotenv()
os.environ["GRID_URL"] = "http://localhost:4444/wd/hub"

# Import functions from your actual modules (match Docker container structure)
from scraper.scraping_functions import (
    retrieve_product_data,
    extract_price_info,
    handle_singular_product,
    does_product_exist,
    is_cookie_valid
)

from hafele_login import handle_login as hafele_login
from core.config import Hafele_BASE_URL, Hafele_LOGIN_URL, Hafele_PRODUCT_API_PATH, Hafele_SEARCH_API_PATH

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COOKIE_FILE = os.path.join(PROJECT_ROOT, "shared", "cookies.pkl")
BASE_PRODUCT_URL = f"{Hafele_BASE_URL}{Hafele_PRODUCT_API_PATH}"


def validate_cookies(cookies):
    """Test if cookies are valid by making a simple request to the site."""
    if not cookies:
        return False, "No cookies provided"
    
    try:
        session = requests.Session()
        
        # Convert cookies to the format expected by requests
        if isinstance(cookies, list):
            for cookie in cookies:
                session.cookies.set(cookie['name'], cookie['value'])
        elif isinstance(cookies, dict):
            session.cookies.update(cookies)
        else:
            return False, f"Invalid cookie format: {type(cookies)}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        # Try to access a page that requires authentication
        test_url = f"{Hafele_LOGIN_URL}/"
        response = session.get(test_url, headers=headers, timeout=30)
        
        print(f"🔍 Cookie validation response status: {response.status_code}")
        
        # Check if we're redirected to login page (indicates invalid cookies)
        if "login" in response.url.lower() or "giriş" in response.url.lower():
            return False, "Redirected to login page - cookies are invalid"
        
        # Check for specific indicators of successful authentication
        if "logout" in response.text.lower() or "çıkış" in response.text.lower():
            return True, "Cookies appear to be valid"
        
        # Check for user-specific content
        if "account" in response.text.lower() or "hesabım" in response.text.lower():
            return True, "Cookies appear to be valid"
            
        return False, "Could not determine cookie validity"
        
    except Exception as e:
        return False, f"Error validating cookies: {e}"


def load_cookies():
    try:
        print("🔄 Starting login process...")
        driver = hafele_login.handle_login()
        cookies = driver.get_cookies()
        driver.quit()
        
        print(f"✅ Successfully obtained {len(cookies)} cookies")
        
        # Validate the cookies immediately after obtaining them
        is_valid, message = validate_cookies(cookies)
        if not is_valid:
            print(f"❌ Cookies are not valid: {message}")
            return None
        
        print(f"✅ Cookies validated: {message}")
        
        # Save cookies
        os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)
        with open(COOKIE_FILE, "wb") as file:
            pickle.dump(cookies, file)
        
        print(f"💾 Cookies saved to {COOKIE_FILE}")
        return cookies
        
    except Exception as e:
        print(f"❌ Failed to load cookies: {e}")
        print("🔍 Check the debug screenshots if they were created")
        return None


def load_existing_cookies():
    """Load existing cookies from file and validate them."""
    try:
        if not os.path.exists(COOKIE_FILE):
            print("❌ Cookie file does not exist")
            return None
            
        # Check if cookies are still valid (not expired)
        if not is_cookie_valid(COOKIE_FILE, 600):  # 10 minutes expiry
            print("⚠️ Cookies have expired")
            return None
            
        with open(COOKIE_FILE, "rb") as file:
            cookies = pickle.load(file)
            
        print(f"📂 Loaded {len(cookies)} cookies from file")
        
        # Validate the loaded cookies
        is_valid, message = validate_cookies(cookies)
        if not is_valid:
            print(f"❌ Loaded cookies are not valid: {message}")
            return None
            
        print(f"✅ Loaded cookies are valid: {message}")
        return cookies
        
    except Exception as e:
        print(f"❌ Error loading existing cookies: {e}")
        return None


def fetch_product_page(url, cookies):
    session = requests.Session()
    
    # Convert cookies to the format expected by requests
    if isinstance(cookies, list):
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'])
    elif isinstance(cookies, dict):
        session.cookies.update(cookies)

    headers = {"User-Agent": "Mozilla/5.0"}
    response = session.get(url, headers=headers, timeout=30)

    if response.status_code == 200:
        return response.text
    else:
        print(f"❌ Failed to fetch product page. Status: {response.status_code}")
        return None


def test_all_functions(product_code, cookies):
    print(f"\n🔍 Testing code: {product_code}")

    # First, validate cookies before testing
    is_valid, message = validate_cookies(cookies)
    if not is_valid:
        print(f"❌ Cannot test with invalid cookies: {message}")
        return

    # Construct product data URL
    url = f"{BASE_PRODUCT_URL}?SKU={product_code.replace('.', '')}&ProductQuantity=20000"

    # Test retrieve_product_data
    try:
        data = retrieve_product_data(url=url, cookie_information=cookies)
        print("✅ retrieve_product_data:", data)
    except Exception as e:
        print("❌ retrieve_product_data error:", e)

    # Fetch page HTML
    html = fetch_product_page(url, cookies)
    if not html:
        print("❌ Could not fetch HTML for further testing")
        return

    soup = BeautifulSoup(html, "html.parser")

    # Test handle_singular_product
    try:
        result = handle_singular_product(soup)
        print("✅ handle_singular_product:", result)
    except Exception as e:
        print("❌ handle_singular_product error:", e)

    # Test extract_price_info
    try:
        price = extract_price_info(soup)
        print("✅ extract_price_info:", price)
    except Exception as e:
        print("❌ extract_price_info error:", e)

    # Test does_product_exist
    try:
        exists = does_product_exist(product_code, cookies)
        print("✅ does_product_exist:", exists[0])
    except Exception as e:
        print("❌ does_product_exist error:", e)


def main():
    # Check if Selenium service is running
    try:
        import requests
        response = requests.get("http://localhost:4444/status", timeout=5)
        if response.status_code == 200:
            print("✅ Selenium service is running")
        else:
            print("⚠️ Selenium service responded with unexpected status")
    except Exception as e:
        print(f"❌ Selenium service is not running: {e}")
        print("💡 Make sure to start the Selenium service with: docker-compose up selenium")
        return
    
    # Try to load existing cookies first
    cookies = load_existing_cookies()
    
    # If no valid existing cookies, perform login
    if not cookies:
        print("🔄 No valid existing cookies found, performing login...")
        cookies = load_cookies()
        
    if not cookies:
        print("❌ Failed to get valid cookies.")
        return

    product_code = input("Enter a product code to test (e.g., 941.30.011): ").strip()
    test_all_functions(product_code, cookies)


if __name__ == "__main__":
    main()
