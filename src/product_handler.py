"""
product_handler.py
------------------
Responsible for:
- Handling singular products (stock extraction + price + description)
- Handling group/set products (sub-product stock aggregation)
- Fetching stock for individual sub-products via Selenium

Depends on: parsers.py, page_loader.py
"""

from bs4 import BeautifulSoup
from src.parsers import extract_price_info, extract_product_description
from src.page_loader import wait_for_element_or_error

from src.util.logger_util import CustomLogger

log_manager = CustomLogger(__name__, log_file="product_handler.log")
logger = log_manager.get_logger()

BASE_PRODUCT_URL = (
    "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY"
    "/ViewProduct-GetPriceAndAvailabilityInformationPDS"
)


def handle_singular_product(soup: BeautifulSoup, search_soup: BeautifulSoup = None) -> dict:
    """
    Extract all data for a singular (non-set) product.

    Args:
        soup:        BeautifulSoup of the product API page
        search_soup: Optional BeautifulSoup of the search/direct page
                     (used for richer description extraction)

    Returns:
        dict with price info, stok_durumu, stock_amount, product_description
    """
    price_info   = extract_price_info(soup)
    stock_amount, stock_status = _extract_stock(soup)
    description  = extract_product_description(search_soup or soup)

    return {
        **price_info,
        "stok_durumu":       stock_status,
        "stock_amount":      stock_amount,
        "product_description": description,
    }


def handle_group_product(driver, soup: BeautifulSoup, search_soup: BeautifulSoup = None) -> dict:
    """
    Extract all data for a group/set product.

    Sub-product stocks are fetched sequentially on the same driver tab
    that is already active — avoids interfering with the round-robin pool.

    Args:
        driver:      Selenium WebDriver (already on the correct tab)
        soup:        BeautifulSoup of the group product page
        search_soup: Optional BeautifulSoup for description extraction

    Returns:
        dict with price info, stok_durumu='set urun', stock_amount, product_description
    """
    sub_rows   = soup.select(".BomArticlesTable .productDataTableQty")
    sub_stocks = []

    for row in sub_rows:
        sku_el = row.find("a", class_="product-sku-title")
        if sku_el:
            sku = sku_el.text.strip().replace(".", "")
            sub_url = f"{BASE_PRODUCT_URL}?SKU={sku}&ProductQuantity=20000&SynchronizationAjaxToken=1"
            stock = _retrieve_singular_stock(driver, sub_url)
            if stock is not None:
                sub_stocks.append(stock)

    price_info  = extract_price_info(soup)
    description = extract_product_description(search_soup or soup)

    return {
        **price_info,
        "stok_durumu": "set urun",
        "stock_amount": min(sub_stocks) if sub_stocks else None,
        "product_description": description,
    }


# ── private helpers ───────────────────────────────────────────────────────────

def _extract_stock(soup: BeautifulSoup):
    """
    Parse stock quantity and status from a singular product page.

    Returns:
        (stock_amount: int | None, stock_status: str)
    """
    stock_amount = None
    stock_status = None

    logger.info("\n🔍 DEBUG: Extracting stock data...\n")
    logger.info("\n🔍 DEBUG: Extracting stock data...\n")

    for row in soup.select("tr.values-tr"):
        qty_el = row.select_one("td.qty-available")
        avail_el = row.select_one("td.requestedPackageStatus .availability-flag")

        if not (qty_el and avail_el):
            continue

        raw_qty = qty_el.text.strip()
        availability_text = avail_el.text.strip().lower()
        qty = int(raw_qty) if raw_qty.isdigit() else None

        logger.info(f"  Found stock: {raw_qty}, Status: {availability_text}")
        logger.info(f"  Found stock: {raw_qty}, Status: {availability_text}")

        if "stokta mevcut" in availability_text:
            logger.info(f"  ✅ Prioritizing 'stokta mevcut' stock: {qty}")
            logger.info(f"  ✅ Prioritizing 'stokta mevcut' stock: {qty}")
            return qty, "stokta mevcut"

        if stock_amount is None:
            stock_amount = qty
            stock_status = availability_text

    # Fallback: read from the availability flag element
    if stock_status is None:
        el = soup.select_one("#productAvailabilityInformation .availability-flag")
        stock_status = el.text.strip() if el else "Stok bilgisi bulunamadi"

    logger.info(f"  📌 Final Stock Amount: {stock_amount}, Status: {stock_status}\n")
    logger.info(f"  📌 Final Stock Amount: {stock_amount}, Status: {stock_status}\n")
    return stock_amount, stock_status


def _retrieve_singular_stock(driver, url: str):
    """
    Navigate to a sub-product URL and return its available stock quantity.

    Returns:
        int stock quantity if 'stokta mevcut', 0 if unavailable, None on error
    """
    try:
        driver.get(url)
        wait_for_element_or_error(driver)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        flag = soup.select_one("span.availability-flag[style='color:#339C76']")

        if flag and "stokta mevcut" in flag.text.strip().lower():
            qty_el = soup.select_one(".qty-available")
            if qty_el and qty_el.text.strip().isdigit():
                return int(qty_el.text.strip())
            return None

        return 0

    except Exception as e:
        logger.exception(f"  Error fetching sub-product stock from {url}: {e}")
        logger.exception(f"  Error fetching sub-product stock from {url}: {e}")
        return None