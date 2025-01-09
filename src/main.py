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

def load_cookies(cookie_file):
    """Load cookies from the saved file."""
    with open(cookie_file, "rb") as file:
        cookies = pickle.load(file)
    return {cookie['name']: cookie['value'] for cookie in cookies}


def retrieve_product_info(url, cookies, retries=3):
    """Fetch and parse the HTML to extract product information with retries."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }

    for attempt in range(retries):
        try:
            print(f"Requesting URL: {url}")
            response = requests.get(url, headers=headers, cookies=cookies, timeout=30)

            if response.status_code == 200:
                # Parse the HTML response
                soup = BeautifulSoup(response.text, "html.parser")

                # Extract price details
                prices = soup.select(".pricedisplay")
                kdv_haric_tavsiye_edilen_perakende_fiyat = (
                    prices[0].select_one(".price").text.strip() if len(prices) > 0 else None
                )
                kdv_haric_net_fiyat = (
                    prices[1].select_one(".price").text.strip() if len(prices) > 1 else None
                )
                kdv_haric_satis_fiyati = (
                    prices[2].select_one(".price").text.strip() if len(prices) > 2 else None
                )

                # Extract availability flag
                stok_durumu_element = soup.select_one(".availability-flag")
                stok_durumu = stok_durumu_element.text.strip() if stok_durumu_element else None

                # Extract stock amounts
                stock_amount_elements = soup.select(".qty-available")
                stock_amounts = [
                    int(element.text.strip()) for element in stock_amount_elements if element.text.strip().isdigit()
                ]
                stock_amount = stock_amounts[0] if stock_amounts else None

                return {
                    "kdv_haric_tavsiye_edilen_perakende_fiyat": kdv_haric_tavsiye_edilen_perakende_fiyat,
                    "kdv_haric_net_fiyat": kdv_haric_net_fiyat,
                    "kdv_haric_satis_fiyati": kdv_haric_satis_fiyati,
                    "stok_durumu": stok_durumu,
                    "stock_amount": stock_amount,
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


def fetch_product_data(stock_code, cookies):
    """Construct the URL for a product code and fetch its availability."""
    sanitized_code = stock_code.replace(".", "")  # Remove dots from the stock code for the URL
    base_url = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"
    params = f"?SKU={sanitized_code}&ProductQuantity=50000&SynchronizationAjaxToken=1"
    product_url = base_url + params

    return retrieve_product_info(product_url, cookies)


def handle_login_with_retry():
    """Handle login with retries until successful."""
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


def main():
    # Step 1: Handle login with retry
    handle_login_with_retry()

    # Load cookies and set login refresh timer
    cookies = load_cookies("cookies.pkl")
    last_login_time = time.time()

    # Step 2: Read stock codes from the input Excel file
    input_file = "product_codes.xlsx"
    df = pd.read_excel(input_file, nrows=5)
    stock_codes = df['stockCode'].tolist()

    # Debug the number of products
    print(f"Total stock codes to process: {len(stock_codes)}")

    # Step 3: Process stock codes sequentially
    results = []
    for index, code in enumerate(stock_codes):
        print(f"Processing stock code ({index + 1}/{len(stock_codes)}): {code}")

        # Re-login every 10 minutes
        if time.time() - last_login_time > 600:  # 10 minutes
            print("Refreshing login session...")
            handle_login_with_retry()
            cookies = load_cookies("cookies.pkl")
            last_login_time = time.time()

        # Fetch data and handle errors gracefully
        try:
            product_info = fetch_product_data(code, cookies)
            product_info["stockCode"] = code  # Add stock code to the result
            results.append(product_info)
        except Exception as e:
            print(f"Error processing stock code {code}: {e}")
            results.append({
                "stockCode": code,
                "kdv_haric_tavsiye_edilen_perakende_fiyat": None,
                "kdv_haric_net_fiyat": None,
                "kdv_haric_satis_fiyati": None,
                "stok_durumu": "Error fetching data",
                "stock_amount": None,
            })

        time.sleep(5)  # Add a longer delay between requests to avoid rate-limiting

    # Step 4: Save all results to Excel after processing
    output_file = "product_data_results.xlsx"
    output_data = pd.DataFrame(results)

    # Reverse the order of the columns
    output_data = output_data[
        [   "stockCode",
            "stock_amount",
            "stok_durumu",
            "kdv_haric_satis_fiyati",
            "kdv_haric_net_fiyat",
            "kdv_haric_tavsiye_edilen_perakende_fiyat"
        ]
    ]

    output_data.to_excel(output_file, index=False)
    print(f"Results saved to {output_file}")


if __name__ == '__main__':
    main()
