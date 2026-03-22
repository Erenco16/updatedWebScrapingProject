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
import time

from src.util.logger_util import CustomLogger

log_manager = CustomLogger(__name__, log_file="product_handler.log")
logger = log_manager.get_logger()

BASE_PRODUCT_URL = (
    "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY"
    "/ViewProduct-GetPriceAndAvailabilityInformationPDS"
)


def handle_singular_product(soup, search_soup=None):
    price_info = extract_price_info(soup)
    stock_rows = soup.select("tr.values-tr")
    stock_amount = None
    stock_status = None
    logger.debug("\n🔍 DEBUG: Extracting stock data...\n")
    for row in stock_rows:
        stock_qty_element = row.select_one("td.qty-available")
        availability_element = row.select_one("td.requestedPackageStatus .availability-flag")
        if stock_qty_element and availability_element:
            stock_qty = stock_qty_element.text.strip()
            availability_text = availability_element.text.strip().lower()
            logger.debug(f"Found stock: {stock_qty}, Status: {availability_text}")
            stock_qty = int(stock_qty) if stock_qty.isdigit() else None
            if "stokta mevcut" in availability_text:
                stock_amount = stock_qty
                stock_status = "stokta mevcut"
                logger.debug(f"✅ Prioritizing 'stokta mevcut' stock: {stock_amount}")
                break
            if stock_amount is None:
                stock_amount = stock_qty
                stock_status = availability_text
    if stock_status is None:
        stock_info_element = soup.select_one("#productAvailabilityInformation .availability-flag")
        stock_status = stock_info_element.text.strip() if stock_info_element else "Stok bilgisi bulunamadi"
    logger.debug(f"📌 Final Stock Amount: {stock_amount}, Status: {stock_status}\n")
    product_description = extract_product_description(search_soup or soup)
    return {
        **price_info,
        "stok_durumu": stock_status,
        "stock_amount": stock_amount,
        "product_description": product_description,
    }


def handle_group_product(driver, soup, search_soup=None):
    """Handle group product: fetch each sub-product's stock using Selenium."""
    base_url = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"
    sub_product_rows = soup.select(".BomArticlesTable .productDataTableQty")
    sub_product_stocks = []
    for row in sub_product_rows:
        sku_element = row.find("a", class_="product-sku-title")
        if sku_element:
            sub_product_sku = sku_element.text.strip().replace(".", "")
            sub_url = f"{base_url}?SKU={sub_product_sku}&ProductQuantity=20000&SynchronizationAjaxToken=1"
            sub_stock = retrieve_singular_stock(driver, sub_url)
            if sub_stock is not None:
                sub_product_stocks.append(sub_stock)
    main_product_stock = min(sub_product_stocks) if sub_product_stocks else None
    price_info = extract_price_info(soup)
    product_description = extract_product_description(search_soup or soup)
    return {
        **price_info,
        "stok_durumu": "set urun",
        "stock_amount": main_product_stock,
        "product_description": product_description,
    }

def retrieve_singular_stock(driver, url):
    """Fetch singular stock information using Selenium."""
    try:
        driver.get(url)
        time.sleep(2)  # Wait for page to load
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        
        availability_flag = soup.select_one("span.availability-flag[style='color:#339C76']")
        if availability_flag and "stokta mevcut" in availability_flag.text.strip().lower():
            stock_amount = soup.select_one(".qty-available")
            return int(stock_amount.text.strip()) if stock_amount and stock_amount.text.strip().isdigit() else None
        return 0
    except Exception as e:
        logger.exception(f"Error fetching singular stock: {e}")
    return None