"""
scraper.py
----------
Responsible for:
- Fetching a single product page and routing to the correct handler
- Orchestrating the round-robin tab pool scrape across all products
- Retrying failed products after the main pass

Depends on: page_loader.py, product_handler.py
"""

import time
from bs4 import BeautifulSoup

from src.util.logger_util import CustomLogger

log_manager = CustomLogger(__name__, log_file="scraper.log")
logger = log_manager.get_logger()

from src.page_loader import (
    wait_for_page_ready,
    wait_for_element_or_error,
    detect_and_backoff_cloudflare,
)
from src.product_handler import handle_singular_product, handle_group_product

FETCH_FAILED = "FETCH_FAILED"



def retrieve_product_data(driver, url, code, retries=3):
    """
    Fetch and parse the HTML to extract stock, price, and group product information.
    Uses Selenium browser to bypass Cloudflare protection.
    """
    for attempt in range(retries):
        try:
            print(f"Navigating to URL: {url}")
            driver.get(url)
            time.sleep(3)  # Wait for page to load
            
            html = driver.page_source
            soup = BeautifulSoup(html, "html.parser")
            
            exists, search_soup = does_product_exist(driver, code=code)
            if exists:
                group_table = soup.find("tr", id="productBomArticlesInformation")
                return (
                    handle_group_product(driver, soup, search_soup=search_soup)
                    if group_table
                    else handle_singular_product(soup, search_soup=search_soup)
                )
            else:
                return {
                    "kdv_haric_tavsiye_edilen_perakende_fiyat": "urun hafele.com.tr de bulunmuyor",
                    "kdv_haric_net_fiyat": "urun hafele.com.tr de bulunmuyor",
                    "kdv_haric_satis_fiyati": "urun hafele.com.tr de bulunmuyor",
                    "stok_durumu": "urun hafele.com.tr de bulunmuyor",
                    "stock_amount": "urun hafele.com.tr de bulunmuyor",
                    "product_description": "No description available",
                }
        except Exception as e:
            print(f"Error retrieving product data (attempt {attempt + 1}): {e}")
            time.sleep(2 ** attempt)  # Exponential backoff

    print(f"Failed to fetch data after {retries} retries for URL: {url}")
    return {
        "kdv_haric_tavsiye_edilen_perakende_fiyat": None,
        "kdv_haric_net_fiyat": None,
        "kdv_haric_satis_fiyati": None,
        "stok_durumu": None,
        "stock_amount": None,
        "product_description": None,
    }



def does_product_exist(driver, code):
    """
    Check if product exists using Selenium browser navigation.
    Returns (exists: bool, soup: BeautifulSoup)
    """
    print(f"Checking existence of product {code}...")
    url = f"https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewParametricSearch-SimpleOfferSearch?SearchType=all&SearchTerm={code}"
    try:
        driver.get(url)
        time.sleep(2)  # Wait for page to load
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        print(f"Search URL: {url}")
        
        error_message = soup.find("p", class_="headlineStyle4")
        exists = not (error_message and f"{code} için aramanız başarısız oldu." in error_message.text)
        return exists, soup
    except Exception as e:
        print(f"Error checking product existence: {e}")
        raise