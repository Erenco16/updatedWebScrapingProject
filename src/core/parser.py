import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bs4 import BeautifulSoup
from scraper.scraping_functions import (
    retrieve_product_data,
    extract_price_info,
    handle_singular_product,
    does_product_exist
)
from fetcher import fetch_product_page_selenium


def parse_product(product_code: str, cookies: list, base_url: str) -> dict:
    """
    Process a single product code: fetch HTML, run all parsing functions.

    :param product_code: SKU code of the product.
    :param cookies: List of cookie dicts from Selenium.
    :param base_url: Hafele product endpoint base URL.
    :return: Dictionary with extracted data and any errors.
    """
    url = f"{base_url}?SKU={product_code.replace('.', '')}&ProductQuantity=20000"

    product_data = {
        "code": product_code,
        "url": url,
        "metadata": None,
        "price_info": None,
        "details": None,
        "exists": None,
        "errors": {}
    }

    # Try metadata API call
    try:
        product_data["metadata"] = retrieve_product_data(url=url, code=product_code, cookie_information=cookies)
    except Exception as e:
        product_data["errors"]["metadata"] = str(e)

    # Try HTML-based parsing
    try:
        html = fetch_product_page_selenium(url, cookies)
        soup = BeautifulSoup(html, "html.parser")

        try:
            product_data["exists"] = does_product_exist(product_code, cookies)
        except Exception as e:
            product_data["errors"]["existence_check"] = str(e)

        try:
            product_data["price_info"] = extract_price_info(soup)
        except Exception as e:
            product_data["errors"]["price_info"] = str(e)

        try:
            product_data["details"] = handle_singular_product(soup)
        except Exception as e:
            product_data["errors"]["details"] = str(e)

    except Exception as e:
        product_data["errors"]["html_fetch"] = str(e)

    return product_data
