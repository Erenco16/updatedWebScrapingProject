import login
import requests
import pickle
from bs4 import BeautifulSoup
import pandas as pd
import time
import os
from dotenv import load_dotenv
from send_mail import send_mail_with_excel
import random
import threading

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

load_dotenv()

COOKIE_FILE = "cookies.pkl"
INPUT_FILE = "/src/input/product_codes.xlsx"  # Use absolute path for consistency
OUTPUT_FILE = "/src/output/product_data_results.xlsx"  # Use absolute path for consistency
COOKIE_EXPIRY = 600  # 10 minutes
LOGIN_INTERVAL = 300 # 5 min

stop_refreshing = False  # Global flag to stop the login refresh loop

def refresh_login():
    """Login every 5 minutes to refresh cookies while scraping is running."""
    global cookies
    while not stop_refreshing:  # Only run while scraping is active
        print("\n🔄 Refreshing login and updating cookies...\n")
        try:
            driver = login.handle_login()
            driver.quit()
            print("✅ Login successful.")
        except Exception as e:
            print(f"❌ Login failed: {e}")

        if os.path.exists(COOKIE_FILE):
            cookies = load_cookies(COOKIE_FILE)
        else:
            print("⚠️ Warning: Cookies file not found after login.")

        # Wait 5 minutes before next login refresh
        for _ in range(LOGIN_INTERVAL // 5):  # Check every 5 seconds if scraping has finished
            if stop_refreshing:
                print("🛑 Stopping login refresh thread.")
                return
            time.sleep(5)

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


# checking the existence of the product by sending a request to the search endpoint,
# being different from our general scraping logic
def does_product_exist(code, cookies):
    print(f"Checking existence of product {code}...")
    # Define the URL and search term
    url = f"https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewParametricSearch-SimpleOfferSearch?SearchType=all&SearchTerm={code}"

    # Send a GET request to the URL
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    # Ensure cookies are in the correct format (convert list of dicts to a single dict)
    if isinstance(cookies, list):
        cookies = {cookie["name"]: cookie["value"] for cookie in cookies}

    # Perform the request
    response = requests.get(url, headers=headers, cookies=cookies)
    print(f"Url for search {url}")
    if response.status_code != 200:
        raise Exception(f"Failed to fetch the URL, status code: {response.status_code}")

    # Parse the response HTML using BeautifulSoup
    soup = BeautifulSoup(response.text, "html.parser")

    # Locate the specific element
    error_message = soup.find("p", class_="headlineStyle4")

    # Check if the error message contains the code
    if error_message and f"{code} için aramanız başarısız oldu." in error_message.text:
        # The product does not exist if the error message is found
        return False

    # If the error message is not found, the product exists
    return True



def handle_singular_product(soup):
    """Handle singular product data extraction, prioritizing 'stokta mevcut' stock amount."""
    price_info = extract_price_info(soup)

    stock_rows = soup.select("tr.values-tr")  # Select all stock rows
    stock_amount = None  # Default value
    stock_status = None  # Default stock status

    print("\n🔍 DEBUG: Extracting stock data...\n")

    for row in stock_rows:
        stock_qty_element = row.select_one("td.qty-available")
        availability_element = row.select_one("td.requestedPackageStatus .availability-flag")

        if stock_qty_element and availability_element:
            stock_qty = stock_qty_element.text.strip()
            availability_text = availability_element.text.strip().lower()

            print(f"Found stock: {stock_qty}, Status: {availability_text}")  # Debug print

            # Convert stock quantity to integer safely
            stock_qty = int(stock_qty) if stock_qty.isdigit() else None

            # If "stokta mevcut" is found, prioritize it and return immediately
            if "stokta mevcut" in availability_text:
                stock_amount = stock_qty
                stock_status = "stokta mevcut"  # Ensuring it doesn't get overwritten later
                print(f"✅ Prioritizing 'stokta mevcut' stock: {stock_amount}")
                break  # Stop searching since we found "stokta mevcut"

            # If no "stokta mevcut" found, use the first available stock as fallback
            if stock_amount is None:
                stock_amount = stock_qty
                stock_status = availability_text  # Store the first found status

    # If no "stokta mevcut" stock was found, fallback to product availability
    if stock_status is None:
        stock_info_element = soup.select_one("#productAvailabilityInformation .availability-flag")
        stock_status = stock_info_element.text.strip() if stock_info_element else "Stok bilgisi bulunamadi"

    print(f"📌 Final Stock Amount: {stock_amount}, Status: {stock_status}\n")  # Final debug print

    return {
        **price_info,
        "stok_durumu": stock_status,
        "stock_amount": stock_amount,
    }


def handle_group_product(soup, cookies):
    """Handle group product data extraction."""
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

    # Determine the main product stock as the minimum of all sub-product stocks
    main_product_stock = min(sub_product_stocks) if sub_product_stocks else None

    # Extract prices (same as singular product)
    price_info = extract_price_info(soup)

    return {
        **price_info,
        "stok_durumu": "set urun",
        "stock_amount": main_product_stock,
    }


def retrieve_singular_stock(url, cookies):
    """Fetch stock information for a singular product with a specific availability filter."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }

    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=60)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")

            # Check for the availability condition
            availability_flag = soup.select_one("span.availability-flag[style='color:#339C76']")
            if availability_flag and "stokta mevcut" in availability_flag.text.strip().lower():
                # Extract the stock amount if the condition is met
                stock_amount = soup.select_one(".qty-available")
                return int(stock_amount.text.strip()) if stock_amount and stock_amount.text.strip().isdigit() else None

            # If the condition is not met, return 0
            return 0

    except Exception as e:
        print(f"Error fetching singular stock: {e}")
    return None

def extract_price_info(soup):
    """Extract price information from the soup."""
    prices = soup.select("span.price")
    units = soup.select("span.perUnit")

    return {
        "kdv_haric_tavsiye_edilen_perakende_fiyat": prices[2].text.strip() if len(prices) > 2 else None,
        "kdv_haric_net_fiyat": prices[0].text.strip() if len(prices) > 0 else None,
        "kdv_haric_satis_fiyati": prices[1].text.strip() if len(prices) > 1 else None,
    }


def get_random_headers():
    """Return random headers to avoid detection."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
    }

def load_cookies(cookie_file):
    """Load cookies from the saved file."""
    with open(cookie_file, "rb") as file:
        cookies = pickle.load(file)
    return {cookie['name']: cookie['value'] for cookie in cookies}

def is_cookie_valid(cookie_file, expiry_time):
    """Check if the cookies file exists and is not expired."""
    return (
        os.path.exists(cookie_file)
        and (time.time() - os.path.getmtime(cookie_file)) < expiry_time
    )

def main():
    """Run the scraper while refreshing login in parallel."""
    global cookies

    # Start login refresher thread
    login_thread = threading.Thread(target=refresh_login, daemon=True)
    login_thread.start()  # This runs in the background without blocking execution

    # Load cookies
    if os.path.exists(COOKIE_FILE):
        cookies = load_cookies(COOKIE_FILE)
    else:
        print("\n❌ No valid cookies found. Performing initial login...\n")
        login.handle_login()  # Only login once if cookies are missing

    # Read stock codes from Excel
    df = pd.read_excel(INPUT_FILE)
    stock_codes = df["stockCode"].tolist()

    # Prepare URLs
    base_url = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"
    product_urls = [(f"{base_url}?SKU={code.replace('.', '')}&ProductQuantity=20000", code) for code in stock_codes]

    # Scrape data
    results = []
    for url, code in product_urls:
        try:
            print(f"Scraping data for stock code {code}...")
            result = retrieve_product_data(url=url, code=code, cookie_information=cookies)
            result["stockCode"] = code
            results.append(result)
        except Exception as e:
            print(f"Error processing stock code {code}: {e}")
            results.append({"stockCode": code, "stok_durumu": f"Error: {e}", "stock_amount": None})

    # Save results to Excel
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)

    output_data = pd.DataFrame(results)
    output_data.to_excel(OUTPUT_FILE, index=False)
    print(f"✅ Results saved to {OUTPUT_FILE}")

    # Send email with results
    email = os.getenv("gmail_receiver_email_2")
    email_2 = os.getenv("gmail_receiver_email")
    try:
        send_mail_with_excel(email, OUTPUT_FILE)
        send_mail_with_excel(email_2, OUTPUT_FILE)
        print(f"📧 Email sent to {email} and {email_2}")
    except Exception as e:
        print(f"❌ Error sending email: {e}")

    print(f"\n✅ Scraping complete. Process will exit now.\n")

if __name__ == "__main__":
    main()
