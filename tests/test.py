import sys
import os
import time
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src import login
from src.selenium_client import make_driver
from src.main import (
    handle_singular_product,
    handle_group_product,
    retrieve_product_data,
    extract_price_info,
    does_product_exist,
    extract_product_description,
    retrieve_singular_stock,
)

BASE_PRODUCT_URL = (
    "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY"
    "/ViewProduct-GetPriceAndAvailabilityInformationPDS"
)


# ── helpers ──────────────────────────────────────────────────────────────────

def build_product_url(code: str) -> str:
    return f"{BASE_PRODUCT_URL}?SKU={code.replace('.', '')}&ProductQuantity=20000"


def get_soup(driver, url: str) -> BeautifulSoup:
    driver.get(url)
    time.sleep(2)
    return BeautifulSoup(driver.page_source, "html.parser")


# ── individual test functions ─────────────────────────────────────────────────

def test_does_product_exist(driver, code: str):
    print("\n" + "=" * 60)
    print("TEST: does_product_exist()")
    print("=" * 60)
    try:
        exists, soup = does_product_exist(driver=driver, code=code)
        print(f"  exists        : {exists}")
        if soup:
            title = soup.title.string if soup.title else "N/A"
            print(f"  page title    : {title}")
            products = soup.find_all("div", class_="productDataTableRow")
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
            is_html = "<!DOCTYPE html>" in result or "<div" in result
            print(f"  HTML output       : {is_html}")
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
        for k, v in result.items():
            if k == "product_description":
                length = len(v) if v and v != "No description available" else 0
                print(f"  product_description: [HTML, {length} chars]" if length else f"  product_description: {v}")
            else:
                print(f"  {k}: {v}")
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
        for k, v in result.items():
            if k == "product_description":
                length = len(v) if v and v != "No description available" else 0
                print(f"  product_description: [HTML, {length} chars]" if length else f"  product_description: {v}")
            else:
                print(f"  {k}: {v}")
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
        for k, v in result.items():
            if k == "product_description":
                length = len(v) if v and v != "No description available" else 0
                print(f"  product_description: [HTML, {length} chars]" if length else f"  product_description: {v}")
            else:
                print(f"  {k}: {v}")
        return result
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        import traceback; traceback.print_exc()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    product_code = input("Enter product code to test (e.g., 806.68.713): ").strip()
    product_url  = build_product_url(product_code)

    print(f"\n🔗 Product URL : {product_url}")

    # ── driver + login ────────────────────────────────────────────────────────
    print("\n📱 Creating Selenium driver...")
    driver = make_driver()

    print("🔐 Logging in...")
    login.handle_login(driver=driver)

    try:
        # ── 1. does_product_exist ─────────────────────────────────────────────
        exists, search_soup = test_does_product_exist(driver, product_code)

        if not exists:
            print("\n⚠️  Product not found on hafele.com.tr — skipping remaining tests.")
            return

        # ── 2. fetch product page soup ────────────────────────────────────────
        print(f"\n🌐 Fetching product page: {product_url}")
        product_soup = get_soup(driver, product_url)

        # ── 3. extract_price_info ─────────────────────────────────────────────
        test_extract_price_info(product_soup)

        # ── 4. extract_product_description (product page) ─────────────────────
        test_extract_product_description(product_soup, label="[from product page]")

        # ── 5. extract_product_description (search page) ─────────────────────
        if search_soup:
            test_extract_product_description(search_soup, label="[from search page]")

        # ── 6. detect product type and run appropriate handler ─────────────────
        group_table = product_soup.find("tr", id="productBomArticlesInformation")

        if group_table:
            print("\nℹ️  Group product detected.")
            test_handle_group_product(driver, product_soup, search_soup=search_soup)
        else:
            print("\nℹ️  Singular product detected.")
            test_handle_singular_product(product_soup, search_soup=search_soup)

        # ── 7. full pipeline ──────────────────────────────────────────────────
        test_retrieve_product_data(driver, product_url, product_code)

    finally:
        driver.quit()
        print("\n✅ Driver closed. Tests complete.")


if __name__ == "__main__":
    main()