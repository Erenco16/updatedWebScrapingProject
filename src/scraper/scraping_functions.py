import requests
import pickle
from bs4 import BeautifulSoup
import time
import os
from dotenv import load_dotenv
import random

load_dotenv()

# Define base directory and update file paths
BASE_DIR = os.path.dirname(__file__)
COOKIE_FILE = os.path.join(BASE_DIR, "cookies.pkl")
INPUT_FILE = os.path.join(BASE_DIR, "input", "product_codes.xlsx")
OUTPUT_FILE = os.path.join(BASE_DIR, "output", "product_data_results.xlsx")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:93.0) Gecko/20100101 Firefox/93.0",
]

PROXIES = [
    "http://185.200.38.194:8080",
    "http://188.132.222.28:8080",
    "http://149.86.159.4:8080",
]

COOKIE_EXPIRY = 600  # 10 minutes
LOGIN_INTERVAL = 300  # 5 min

stop_refreshing = False  # Global flag to stop the hafele_login refresh loop


def retrieve_product_data(url, code, cookie_information, retries=3):
    """Fetch and parse the HTML to extract stock, price, and group product information."""
    for attempt in range(retries):
        try:
            headers = get_random_headers()
            print(f"Requesting URL: {url}")

            # Convert cookies list to dictionary if necessary
            if isinstance(cookie_information, list):
                cookie_information = {cookie['name']: cookie['value'] for cookie in cookie_information}

            response = requests.get(url, headers=headers, cookies=cookie_information, timeout=60)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                if does_product_exist(code=code, cookies=cookie_information):
                    group_table = soup.find("tr", id="productBomArticlesInformation")
                    return handle_group_product(soup, cookie_information) if group_table else handle_singular_product(soup)
                else:
                    return {
                        "kdv_haric_tavsiye_edilen_perakende_fiyat": "urun hafele.com.tr de bulunmuyor",
                        "kdv_haric_net_fiyat": "urun hafele.com.tr de bulunmuyor",
                        "kdv_haric_satis_fiyati": "urun hafele.com.tr de bulunmuyor",
                        "stok_durumu": "urun hafele.com.tr de bulunmuyor",
                        "stock_amount": "urun hafele.com.tr de bulunmuyor",
                    }
            else:
                print(f"Request failed with status {response.status_code}. Retrying...")
        except requests.exceptions.RequestException as e:
            print(f"Request error: {e}. Retrying...")

        time.sleep(2 ** attempt)  # Exponential backoff

    print(f"Failed to fetch data after {retries} retries for URL: {url}")
    return {
        "kdv_haric_tavsiye_edilen_perakende_fiyat": None,
        "kdv_haric_net_fiyat": None,
        "kdv_haric_satis_fiyati": None,
        "stok_durumu": None,
        "stock_amount": None,
    }

def does_product_exist(code, cookies):
    print(f"Checking existence of product {code}...")
    url = f"https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewParametricSearch-SimpleOfferSearch?SearchType=all&SearchTerm={code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    if isinstance(cookies, list):
        cookies = {cookie["name"]: cookie["value"] for cookie in cookies}

    response = requests.get(url, headers=headers, cookies=cookies)
    print(f"Url for search {url}")
    if response.status_code != 200:
        raise Exception(f"Failed to fetch the URL, status code: {response.status_code}")

    soup = BeautifulSoup(response.text, "html.parser")
    error_message = soup.find("p", class_="headlineStyle4")
    if error_message and f"{code} için aramanız başarısız oldu." in error_message.text:
        return False
    return True

def handle_singular_product(soup):
    price_info = extract_price_info(soup)
    stock_rows = soup.select("tr.values-tr")
    stock_amount = None
    stock_status = None
    print("\n🔍 DEBUG: Extracting stock data...\n")
    for row in stock_rows:
        stock_qty_element = row.select_one("td.qty-available")
        availability_element = row.select_one("td.requestedPackageStatus .availability-flag")
        if stock_qty_element and availability_element:
            stock_qty = stock_qty_element.text.strip()
            availability_text = availability_element.text.strip().lower()
            print(f"Found stock: {stock_qty}, Status: {availability_text}")
            stock_qty = int(stock_qty) if stock_qty.isdigit() else None
            if "stokta mevcut" in availability_text:
                stock_amount = stock_qty
                stock_status = "stokta mevcut"
                print(f"✅ Prioritizing 'stokta mevcut' stock: {stock_amount}")
                break
            if stock_amount is None:
                stock_amount = stock_qty
                stock_status = availability_text
    if stock_status is None:
        stock_info_element = soup.select_one("#productAvailabilityInformation .availability-flag")
        stock_status = stock_info_element.text.strip() if stock_info_element else "Stok bilgisi bulunamadi"
    print(f"📌 Final Stock Amount: {stock_amount}, Status: {stock_status}\n")
    return {
        **price_info,
        "stok_durumu": stock_status,
        "stock_amount": stock_amount,
    }

def handle_group_product(soup, cookies):
    base_url = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"
    sub_product_rows = soup.select(".BomArticlesTable .productDataTableQty")
    sub_product_stocks = []
    for row in sub_product_rows:
        sku_element = row.find("a", class_="product-sku-title")
        if sku_element:
            sub_product_sku = sku_element.text.strip().replace(".", "")
            sub_url = f"{base_url}?SKU={sub_product_sku}&ProductQuantity=20000&SynchronizationAjaxToken=1"
            sub_stock = retrieve_singular_stock(sub_url, cookies)
            if sub_stock is not None:
                sub_product_stocks.append(sub_stock)
    main_product_stock = min(sub_product_stocks) if sub_product_stocks else None
    price_info = extract_price_info(soup)
    return {
        **price_info,
        "stok_durumu": "set urun",
        "stock_amount": main_product_stock,
    }

def retrieve_singular_stock(url, cookies):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }
    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=60)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            availability_flag = soup.select_one("span.availability-flag[style='color:#339C76']")
            if availability_flag and "stokta mevcut" in availability_flag.text.strip().lower():
                stock_amount = soup.select_one(".qty-available")
                return int(stock_amount.text.strip()) if stock_amount and stock_amount.text.strip().isdigit() else None
            return 0
    except Exception as e:
        print(f"Error fetching singular stock: {e}")
    return None

def extract_price_info(soup):
    prices = soup.select("span.price")
    units = soup.select("span.perUnit")
    return {
        "kdv_haric_tavsiye_edilen_perakende_fiyat": prices[2].text.strip() if len(prices) > 2 else None,
        "kdv_haric_net_fiyat": prices[0].text.strip() if len(prices) > 0 else None,
        "kdv_haric_satis_fiyati": prices[1].text.strip() if len(prices) > 1 else None,
    }

def get_random_headers():
    return {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-GB,en;q=0.9,tr;q=0.5",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Ch-Ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"'
}

def is_cookie_valid(cookie_file, expiry_time):
    return (
        os.path.exists(cookie_file)
        and (time.time() - os.path.getmtime(cookie_file)) < expiry_time
    )

def fetch_product_page(url, cookies):
    session = requests.Session()
    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'])

    headers = {"User-Agent": "Mozilla/5.0"}
    response = session.get(url, headers=headers, timeout=30)

    if response.status_code == 200:
        return response.text
    else:
        print(f"❌ Failed to fetch product page. Status: {response.status_code}")
        return None