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


def retrieve_qty_available(url, cookies, retries=3):
    """Fetch and parse the HTML to extract qty-available values with retries."""
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

                # Check if a table exists
                if not soup.find("table"):
                    print(f"No table found on the page: {url}")
                    return "Non existent in hafele.com.tr"

                # Select qty-available elements
                qty_available_elements = soup.select(".qty-available")

                # Extract qty-available values
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

        time.sleep(2 ** attempt)  # Exponential backoff

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
            response = requests.get(url, headers=headers, cookies=cookies, timeout=30)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")

                # Check for group product table
                group_table = soup.find("tr", id="productBomArticlesInformation")
                if group_table:
                    print("Group product detected. Fetching sub-product stock information.")
                    return handle_group_product(soup, cookies)

                # Process singular product
                return handle_singular_product(soup)

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


def handle_group_product(soup, cookies):
    """Handle group product data extraction."""
    base_url = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"
    sub_product_rows = soup.select(".BomArticlesTable .productDataTableQty")
    sub_product_stocks = []

    for row in sub_product_rows:
        sku_element = row.find("a", class_="product-sku-title")
        if sku_element:
            sub_product_sku = sku_element.text.strip().replace(".", "")
            sub_url = f"{base_url}?SKU={sub_product_sku}&ProductQuantity=200000&SynchronizationAjaxToken=1"
            sub_stock = retrieve_singular_stock(sub_url, cookies)
            if sub_stock is not None:
                sub_product_stocks.append(sub_stock)

    # Determine the main product stock as the minimum of all sub-product stocks
    main_product_stock = min(sub_product_stocks) if sub_product_stocks else None

    # Extract prices (same as singular product)
    price_info = extract_price_info(soup)

    return {
        **price_info,
        "stok_durumu": "Group Product",
        "stock_amount": main_product_stock,
    }


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
    prices = soup.select("td.pricedisplay .price")
    kdv_haric_tavsiye_edilen_perakende_fiyat = (
        prices[2].text.strip() if len(prices) > 2 else None
    )
    kdv_haric_net_fiyat = prices[1].text.strip() if len(prices) > 1 else None
    kdv_haric_satis_fiyati = prices[0].text.strip() if len(prices) > 0 else None

    return {
        "kdv_haric_tavsiye_edilen_perakende_fiyat": kdv_haric_tavsiye_edilen_perakende_fiyat,
        "kdv_haric_net_fiyat": kdv_haric_net_fiyat,
        "kdv_haric_satis_fiyati": kdv_haric_satis_fiyati,
    }


def retrieve_singular_stock(url, cookies):
    """Fetch stock information for a singular product."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }

    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=30)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            stock_amount = soup.select_one(".qty-available")
            return int(stock_amount.text.strip()) if stock_amount and stock_amount.text.strip().isdigit() else None
    except Exception as e:
        print(f"Error fetching singular stock: {e}")
    return None



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
    # Base URL for product requests
    base_url = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"

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

        # Construct the full URL for the product
        sanitized_code = code.replace(".", "")  # Remove dots from the stock code
        product_url = f"{base_url}?SKU={sanitized_code}&ProductQuantity=50000&SynchronizationAjaxToken=1"

        # Fetch data and handle errors gracefully
        try:
            product_data = retrieve_product_data(product_url, cookies)
            product_data["stockCode"] = code  # Add stock code as part of the result
            results.append(product_data)
        except Exception as e:
            print(f"Error processing stock code {code}: {e}")
            results.append({
                "stockCode": code,
                "kdv_haric_tavsiye_edilen_perakende_fiyat": None,
                "kdv_haric_net_fiyat": None,
                "kdv_haric_satis_fiyati": None,
                "stok_durumu": "Error",
                "stock_amount": None,
            })

        time.sleep(5)  # Add a longer delay between requests to avoid rate-limiting

    # Step 4: Save all results to Excel after processing
    output_file = "product_data_results.xlsx"
    print(f"Saving {len(results)} results to {output_file}")
    output_data = pd.DataFrame(results)  # Create DataFrame directly from list of dictionaries
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

    # Step 5: Send email with the final results
    email = os.getenv("gmail_receiver_email_2")
    try:
        send_mail_with_excel(email, output_file)
        print(f"Email sent to {email}")
    except Exception as e:
        print(f"Error sending email: {e}")


if __name__ == '__main__':
    main()
