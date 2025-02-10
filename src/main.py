import login
import requests
import pickle
from bs4 import BeautifulSoup
import pandas as pd
import time
import os
from dotenv import load_dotenv
from send_mail import send_mail_with_excel

load_dotenv()

COOKIE_FILE = "cookies.pkl"
INPUT_FILE = "/src/input/product_codes.xlsx"  # Use absolute path for consistency
OUTPUT_FILE = "/src/output/product_data_results.xlsx"  # Use absolute path for consistency
COOKIE_EXPIRY = 600  # 10 minutes

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


def handle_login_with_retry():
    """Handle login and retry on failure."""
    while True:
        try:
            print("Attempting to log in...")
            driver = login.handle_login()
            driver.quit()
            print("Login successful.")
            return
        except Exception as e:
            print(f"Login attempt failed: {e}")
            print("Retrying in 5 seconds...")
            time.sleep(5)


def retrieve_qty_available(url, cookies, retries=3):
    """Fetch and parse the HTML to extract qty-available values with retries."""
    headers = {
        "User-Agent": "Mozilla/5.0",
    }

    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers, cookies=cookies, timeout=60)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                qty_available_elements = soup.select(".qty-available")
                qty_available_values = [
                    int(element.text.strip())
                    for element in qty_available_elements
                    if element.text.strip().isdigit()
                ]
                return qty_available_values[0] if qty_available_values else None
            else:
                print(f"Request failed with status {response.status_code}. Retrying...")
        except requests.exceptions.RequestException as e:
            print(f"Request error: {e}. Retrying...")
        time.sleep(2 ** attempt)

    print(f"Failed to fetch data after {retries} retries for URL: {url}")
    return None


def retrieve_product_data(url, cookies, retries=3):
    """Fetch and parse the HTML to extract stock, price, and group product information."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }

    for attempt in range(retries):
        try:
            print(f"Requesting URL: {url}")
            response = requests.get(url, headers=headers, cookies=cookies, timeout=60)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")

                # check if product exists
                if does_product_exist(soup):
                    # Check for group product table
                    group_table = soup.find("tr", id="productBomArticlesInformation")
                    if group_table:
                        print("Group product detected. Fetching sub-product stock information.")
                        return handle_group_product(soup, cookies)

                    # Process singular product
                    return handle_singular_product(soup)
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

def does_product_exist(soup):
    product_table = soup.find("tr", id="productPriceInformation")
    return product_table is not None


def handle_singular_product(soup):
    """Handle singular product data extraction."""
    price_info = extract_price_info(soup)
    stock_info = soup.select_one(".availability-flag").text.strip()
    stock_amount = soup.select_one(".qty-available")
    stock_amount = int(stock_amount.text.strip()) if stock_amount and stock_amount.text.strip().isdigit() else None

    return {
        **price_info,
        "stok_durumu": stock_info,
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


def main():
    start_time = time.time()

    # Ensure valid cookies
    if not is_cookie_valid(COOKIE_FILE, COOKIE_EXPIRY):
        handle_login_with_retry()

    # Load cookies
    cookies = load_cookies(COOKIE_FILE)


    # Read stock codes from Excel
    # df = pd.read_excel(INPUT_FILE, nrows = 100)
    # print(f"Number of products to be scraped: {len(df)}")
    # stock_codes = df["stockCode"].tolist()

    df = pd.read_excel("/src/input/product_codes.xlsx")
    stock_codes = df["stockCode"].tolist()

    # Prepare URLs
    base_url = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"
    product_urls = [(f"{base_url}?SKU={code.replace('.', '')}&ProductQuantity=50000", code) for code in stock_codes]

    # Scrape data using multithreading
    results = []
    # Single-threaded execution of product data retrieval
    for url, code in product_urls:
        try:
            result = retrieve_product_data(url, cookies)
            result["stockCode"] = code
            results.append(result)
        except Exception as e:
            print(f"Error processing stock code {code}: {e}")
            results.append({"stockCode": code, "stok_durumu": "Error", "stock_amount": None})

    # Save results to Excel
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)  # Ensure no old file exists

    # re arrange the order of the columns of the data
    output_data = pd.DataFrame(results)
    output_data = output_data[
        ["stockCode",
         "stock_amount",
         "stok_durumu",
         "kdv_haric_satis_fiyati",
         "kdv_haric_net_fiyat",
         "kdv_haric_tavsiye_edilen_perakende_fiyat"
         ]
    ]
    output_data.to_excel(OUTPUT_FILE, index=False)
    print(f"Results saved to {OUTPUT_FILE}")

    # Delay to ensure file write completion
    time.sleep(1)

    # Debug logs
    print(f"Sending the file: {OUTPUT_FILE}")
    print(f"File last modified: {time.ctime(os.path.getmtime(OUTPUT_FILE))}")

   # Send email with the results
    email = os.getenv("gmail_receiver_email_2")
    try:
        send_mail_with_excel(email, OUTPUT_FILE)
        print(f"Email sent to {email}")
    except Exception as e:
        print(f"Error sending email: {e}")

    end_time = time.time()
    print(f"Scraped {len(stock_codes)} products in {round((end_time - start_time) / 60, 2)} minutes.")


if __name__ == "__main__":
    main()