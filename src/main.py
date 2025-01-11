import login
import requests
import pickle
from bs4 import BeautifulSoup
import pandas as pd
import time
import os
from dotenv import load_dotenv
from send_mail import send_mail_with_excel
import concurrent.futures

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
            response = requests.get(url, headers=headers, cookies=cookies, timeout=30)
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
        "User-Agent": "Mozilla/5.0",
    }

    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers, cookies=cookies, timeout=30)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                return handle_singular_product(soup)
            else:
                print(f"Request failed with status {response.status_code}. Retrying...")
        except requests.exceptions.RequestException as e:
            print(f"Request error: {e}. Retrying...")
        time.sleep(2 ** attempt)

    print(f"Failed to fetch data after {retries} retries for URL: {url}")
    return {"stok_durumu": "Error", "stock_amount": None}


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
    df = pd.read_excel(INPUT_FILE)
    stock_codes = df["stockCode"].tolist()

    # Prepare URLs
    base_url = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"
    product_urls = [(f"{base_url}?SKU={code.replace('.', '')}&ProductQuantity=50000", code) for code in stock_codes]

    # Scrape data using multithreading
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_code = {executor.submit(retrieve_product_data, url, cookies): code for url, code in product_urls}
        for future in concurrent.futures.as_completed(future_to_code):
            code = future_to_code[future]
            try:
                result = future.result()
                result["stockCode"] = code
                results.append(result)
            except Exception as e:
                print(f"Error processing stock code {code}: {e}")
                results.append({"stockCode": code, "stok_durumu": "Error", "stock_amount": None})

    # Save results to Excel
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)  # Ensure no old file exists

    output_data = pd.DataFrame(results)
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
