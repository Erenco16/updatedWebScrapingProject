import sys
import os
import time
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src import login
from src.selenium_client import make_driver
from src.parsers import extract_price_info, extract_product_description
from src.product_handler import handle_singular_product, handle_group_product
from src.scraper import retrieve_product_data, does_product_exist

BASE_PRODUCT_URL = (
    "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY"
    "/ViewProduct-GetPriceAndAvailabilityInformationPDS"
)


# ── helpers ───────────────────────────────────────────────────────────────────

def build_product_url(code: str) -> str:
    return f"{BASE_PRODUCT_URL}?SKU={code.replace('.', '')}&ProductQuantity=20000"


def get_soup(driver, url: str) -> BeautifulSoup:
    from src.page_loader import wait_for_element_or_error
    driver.get(url)
    html = wait_for_element_or_error(driver)
    return BeautifulSoup(html, "html.parser")


# ── individual test functions ─────────────────────────────────────────────────

def test_does_product_exist(driver, code: str):
    print("\n" + "=" * 60)
    print("TEST: does_product_exist()")
    print("=" * 60)
    try:
        exists, soup = does_product_exist(driver=driver, code=code)
        print(f"  exists        : {exists}")
        if soup:
            title    = soup.title.string if soup.title else "N/A"
            products = soup.find_all("div", class_="productDataTableRow")
            print(f"  page title    : {title}")
            print(f"  products found: {len(products)}")
        return exists, soup
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        import traceback; traceback.print_exc()
        return False, None


def test_extract_price_info(soup: BeautifulSoup):
    print("\n" + "=" * 60)
    print("TEST: extract_price_info()")
    print("=" * 60)
    try:
        result = extract_price_info(soup)
        for k, v in result.items():
            print(f"  {k}: {v}")
        return result
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        import traceback; traceback.print_exc()


def test_extract_product_description(soup: BeautifulSoup, label: str = ""):
    print("\n" + "=" * 60)
    print(f"TEST: extract_product_description() {label}")
    print("=" * 60)
    try:
        result = extract_product_description(soup)
        if not result or result == "No description available":
            print("  ⚠️  No description available")
        else:
            print(f"  HTML output       : {'<div' in result}")
            print(f"  Length (chars)    : {len(result)}")
            print(f"  Has container div : {'product-description-container' in result}")
            print(f"  Has property secs : {'property-section' in result}")
            print(f"  Preview (200 ch)  : {result[:200]}...")
        return result
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        import traceback; traceback.print_exc()


def test_handle_singular_product(soup: BeautifulSoup, search_soup: BeautifulSoup = None):
    print("\n" + "=" * 60)
    print("TEST: handle_singular_product()")
    print("=" * 60)
    try:
        result = handle_singular_product(soup, search_soup=search_soup)
        _print_result(result)
        return result
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        import traceback; traceback.print_exc()


def test_handle_group_product(driver, soup: BeautifulSoup, search_soup: BeautifulSoup = None):
    print("\n" + "=" * 60)
    print("TEST: handle_group_product()")
    print("=" * 60)
    try:
        result = handle_group_product(driver=driver, soup=soup, search_soup=search_soup)
        _print_result(result)
        return result
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        import traceback; traceback.print_exc()


def test_retrieve_product_data(driver, url: str, code: str):
    print("\n" + "=" * 60)
    print("TEST: retrieve_product_data()  [full pipeline]")
    print("=" * 60)
    try:
        result = retrieve_product_data(driver=driver, url=url, code=code)
        _print_result(result)
        return result
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        import traceback; traceback.print_exc()


def _print_result(result: dict):
    for k, v in result.items():
        if k == "product_description":
            length = len(v) if v and v != "No description available" else 0
            print(f"  product_description: [HTML, {length} chars]" if length else f"  product_description: {v}")
        else:
            print(f"  {k}: {v}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    product_code = os.getenv("PRODUCT_CODE") or input("Enter product code to test (e.g., 806.68.713): ").strip()
    print(f"\n🧪 Testing product code: {product_code}")

    product_url = build_product_url(product_code)
    print(f"🔗 Product URL : {product_url}")

    grid_url = os.getenv("GRID_URL", "not set")
    print(f"\n📱 Creating Selenium driver (remote: {grid_url})...")
    driver = make_driver()

    print("🔐 Logging in...")
    login.handle_login(driver=driver)

    try:
        # 1. Existence check
        exists, search_soup = test_does_product_exist(driver, product_code)
        if not exists:
            print("\n⚠️  Product not found — skipping remaining tests.")
            return

        # 2. Fetch product page
        print(f"\n🌐 Fetching product page...")
        product_soup = get_soup(driver, product_url)

        # 3. Parsers
        test_extract_price_info(product_soup)
        test_extract_product_description(product_soup, label="[product page]")
        if search_soup:
            test_extract_product_description(search_soup, label="[search page]")

        # 4. Product type handler
        if product_soup.find("tr", id="productBomArticlesInformation"):
            print("\nℹ️  Group product detected.")
            test_handle_group_product(driver, product_soup, search_soup=search_soup)
        else:
            print("\nℹ️  Singular product detected.")
            test_handle_singular_product(product_soup, search_soup=search_soup)

        # 5. Full pipeline
        test_retrieve_product_data(driver, product_url, product_code)

    finally:
        driver.quit()
        print("\n✅ Driver closed. Tests complete.")


if __name__ == "__main__":
    main()