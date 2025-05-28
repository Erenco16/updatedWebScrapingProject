import os
import sys
import pickle
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Add src directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

# Load environment variables
load_dotenv()
os.environ["GRID_URL"] = "http://localhost:4444/wd/hub"

# Import functions from your actual modules
from src.scraper.scraping_functions import (
    retrieve_product_data,
    extract_price_info,
    handle_singular_product,
    does_product_exist
)

from src.hafele_login import handle_login as hafele_login
COOKIE_FILE = "cookies.pkl"
BASE_PRODUCT_URL = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"


def load_cookies():
    driver = hafele_login.handle_login()
    cookies = driver.get_cookies()
    driver.quit()

    with open(COOKIE_FILE, "wb") as file:
        pickle.dump(cookies, file)

    return cookies


def fetch_product_page(url, cookies):
    session = requests.Session()
    for cookie in cookies:
        print(f"Cookie: {cookie}")
        session.cookies.set(cookie['name'], cookie['value'])

    headers = {"User-Agent": "Mozilla/5.0"}
    response = session.get(url, headers=headers, timeout=30)

    if response.status_code == 200:
        return response.text
    else:
        print(f"❌ Failed to fetch product page. Status: {response.status_code}")
        return None


def test_all_functions(product_code, cookies):
    print(f"\n🔍 Testing code: {product_code}")

    # Construct product data URL
    url = f"{BASE_PRODUCT_URL}?SKU={product_code.replace('.', '')}&ProductQuantity=20000"

    # Test retrieve_product_data
    try:
        data = retrieve_product_data(url=url, code=product_code, cookie_information=cookies)
        print("✅ retrieve_product_data:", data)
    except Exception as e:
        print("❌ retrieve_product_data error:", e)

    # Fetch page HTML
    html = fetch_product_page(url, cookies)
    if not html:
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
        print("✅ does_product_exist:", exists)
    except Exception as e:
        print("❌ does_product_exist error:", e)


def main():
    cookies = load_cookies()
    if not cookies:
        print("❌ Failed to get cookies.")
        return

    product_code = input("Enter a product code to test (e.g., 941.30.011): ").strip()
    test_all_functions(product_code, cookies)


if __name__ == "__main__":
    main()
