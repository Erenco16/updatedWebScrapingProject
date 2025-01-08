from exceptiongroup import catch

import login
import requests
import pickle
from bs4 import BeautifulSoup
import pandas as pd
import time
import os
from dotenv import load_dotenv
import send_mail
from src.send_mail import send_mail_with_excel

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


def fetch_product_data(stock_code, cookies):
    """Construct the URL for a product code and fetch its availability."""
    sanitized_code = stock_code.replace(".", "")  # Remove dots from the stock code for the URL
    base_url = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"
    params = f"?SKU={sanitized_code}&ProductQuantity=50000&SynchronizationAjaxToken=1"
    product_url = base_url + params

    return retrieve_qty_available(product_url, cookies)


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
    df = pd.read_excel(input_file)
    stock_codes = df['stockCode'].tolist()

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
            qty_value = fetch_product_data(code, cookies)
            results.append((code, qty_value))
        except Exception as e:
            print(f"Error processing stock code {code}: {e}")
            results.append((code, "Urun hafele.com.tr da bulunmuyor."))

        time.sleep(5)  # Add a longer delay between requests to avoid rate-limiting

    # Step 4: Save all results to Excel after processing
    output_file = "product_data_results.xlsx"
    output_data = pd.DataFrame(results, columns=["stockCode", "QtyAvailable"])
    output_data.to_excel(output_file, index=False)
    print(f"Results saved to {output_file}")
    email = os.getenv("gmail_receiver_email_2")
    try:
        send_mail_with_excel(email)
        print(f"Email sent to {email}")
    except Exception as e:
        print(f"Error sending email: {e}")
if __name__ == '__main__':
    main()
