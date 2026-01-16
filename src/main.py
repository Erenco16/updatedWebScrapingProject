from src import login
import requests
import pickle
from bs4 import BeautifulSoup
import pandas as pd
import time
import os
from dotenv import load_dotenv
from src.send_mail import send_mail_with_excel, send_mail
import random
import threading

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
                exists, search_soup = does_product_exist(code=code, cookies=cookie_information)
                if exists:
                    group_table = soup.find("tr", id="productBomArticlesInformation")
                    return (
                    handle_group_product(soup, cookie_information, search_soup=search_soup)
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
        "product_description": None,
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
    exists = not (error_message and f"{code} için aramanız başarısız oldu." in error_message.text)
    return exists, soup

def extract_product_description(soup):
    """Extract product description from the product properties section and format as responsive HTML."""
    try:
        # Try multiple ways to find the properties container
        properties_container = soup.find("div", class_="hfl-product-properties-content")
        
        # If not found, try finding the label and getting the next sibling
        if not properties_container:
            label = soup.find("div", class_="hfl-product-properties-label collapse__heading mobileNegativeMargin15")
            if label:
                # The properties content should be a sibling or nearby
                properties_container = label.find_next("div", class_="hfl-product-properties-content")
        
        # Alternative: look for the collapse container
        if not properties_container:
            collapse_div = soup.find("div", class_="collapse in")
            if collapse_div:
                properties_container = collapse_div.find("div", class_="hfl-product-properties-content")
        
        if not properties_container:
            print("⚠️ Could not find properties container")
            return "No description available"
        
        sections = properties_container.find_all("div", class_="productPropertiesSection")
        if not sections:
            print("⚠️ Could not find product property sections")
            return "No description available"
        
        # Extract all product property sections
        html_sections = []
        for section in sections:
            header = section.find("h3", class_="productPropertiesSectionHeader")
            body = section.find("div", class_="productPropertiesSectionBody")
            
            if header and body:
                header_text = header.get_text(strip=True)
                body_text = body.get_text(strip=True)
                html_sections.append({
                    "header": header_text,
                    "body": body_text
                })
            else:
                # Handle sections without headers (like the first introductory section)
                body_text = section.get_text(strip=True)
                if body_text:
                    html_sections.append({
                        "header": None,
                        "body": body_text
                    })
        
        if not html_sections:
            print("⚠️ No html sections extracted")
            return "No description available"
        
        # Build responsive HTML with inline styles
        html_content = '''<style>
    .product-description-container {
        max-width: 800px;
        margin: 0 auto;
    }
    
    @media (max-width: 768px) {
        .product-description-container {
            border-radius: 4px;
            box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
        }
        
        .description-header {
            padding: 15px;
        }
        
        .description-content {
            padding: 15px;
        }
        
        .property-section {
            margin-bottom: 15px;
            padding-bottom: 15px;
        }
        
        .property-header {
            padding: 10px 12px;
            font-size: 14px;
        }
        
        .property-body {
            padding: 0 12px;
            font-size: 13px;
        }
        
        .intro-section {
            padding: 12px;
            margin-bottom: 15px;
            font-size: 13px;
        }
    }
    
    @media (max-width: 480px) {
        .description-header h1 {
            font-size: 18px;
        }
        
        .description-content {
            padding: 12px;
        }
        
        .property-section {
            margin-bottom: 12px;
            padding-bottom: 12px;
        }
        
        .property-header {
            padding: 8px 10px;
            font-size: 13px;
            border-left-width: 3px;
        }
        
        .property-body {
            padding: 0 10px;
            font-size: 12px;
        }
    }
</style>
<div class="product-description-container" style="background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1); overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;">
    <div class="description-header" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; text-align: center;">
        <h1 style="font-size: clamp(20px, 5vw, 28px); font-weight: 600; letter-spacing: 0.5px; margin: 0;">📋 Ürün Özellikleri</h1>
    </div>
    <div class="description-content" style="padding: 20px;">
'''
        
        # Add intro section if it exists (first section without header)
        if html_sections and html_sections[0]["header"] is None:
            html_content += f'        <div class="intro-section" style="background-color: #f0f4ff; padding: 15px; border-radius: 6px; margin-bottom: 20px; border-left: 4px solid #667eea; color: #333333; line-height: 1.6; font-size: clamp(13px, 3.5vw, 15px);">{html_sections[0]["body"]}</div>\n'
            html_sections = html_sections[1:]  # Remove from list
        
        # Add property sections
        for section in html_sections:
            html_content += f'''        <div class="property-section" style="margin-bottom: 20px; padding-bottom: 20px; border-bottom: 1px solid #e0e0e0;">
            <div class="property-header" style="background-color: #f8f9fa; padding: 12px 15px; border-left: 4px solid #667eea; border-radius: 4px; margin-bottom: 12px; font-weight: 600; color: #333333; font-size: clamp(14px, 4vw, 16px);">{section["header"]}</div>
            <div class="property-body" style="padding: 0 15px; color: #555555; line-height: 1.6; font-size: clamp(13px, 3.5vw, 15px); word-break: break-word;">{section["body"]}</div>
        </div>
'''
        
        html_content += '''    </div>
</div>'''
        
        return html_content
    except Exception as e:
        print(f"Error extracting product description: {e}")
        import traceback
        traceback.print_exc()
        return "No description available"

def handle_singular_product(soup, search_soup=None):
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
    product_description = extract_product_description(search_soup or soup)
    return {
        **price_info,
        "stok_durumu": stock_status,
        "stock_amount": stock_amount,
        "product_description": product_description,
    }

def handle_group_product(soup, cookies, search_soup=None):
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
    product_description = extract_product_description(search_soup or soup)
    return {
        **price_info,
        "stok_durumu": "set urun",
        "stock_amount": main_product_stock,
        "product_description": product_description,
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
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
    }

def load_cookies(cookie_file):
    with open(cookie_file, "rb") as file:
        cookies = pickle.load(file)
    return {cookie['name']: cookie['value'] for cookie in cookies}

def is_cookie_valid(cookie_file, expiry_time):
    return (
        os.path.exists(cookie_file)
        and (time.time() - os.path.getmtime(cookie_file)) < expiry_time
    )

def main():
    global cookies, stop_refreshing
    informal_mail = os.getenv("informal_mail")
    
    try:
        # Send scrape started email
        send_mail(
            informal_mail,
            subject="🚀 Hafele Web Scraping Started",
            body="The Hafele web scraping process has started. You will receive another email when it completes."
        )
    except Exception as e:
        print(f"❌ Error sending start email: {e}")
    
    login_thread = threading.Thread(target=refresh_login, daemon=True)
    login_thread.start()

    try:
        if os.path.exists(COOKIE_FILE):
            print("\n✅ Cookies file found. Loading cookies...\n")
            cookies = load_cookies(COOKIE_FILE)
        else:
            print("\n❌ No cookies file found. Logging in to create cookies...\n")
            driver = login.handle_login()
            driver.quit()
            cookies = load_cookies(COOKIE_FILE)

        if cookies is None or not cookies:
            print("⚠️ Warning: Cookies are empty. Login might have failed!")
            error_body = "The Hafele web scraping process failed: Cookies are empty. Login might have failed!"
            try:
                send_mail(
                    informal_mail,
                    subject="❌ Hafele Web Scraping Failed",
                    body=error_body
                )
            except Exception as e:
                print(f"❌ Error sending error email: {e}")
            return

        df = pd.read_excel(INPUT_FILE)
        stock_codes = df["stockCode"].tolist()
    
        base_url = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"
        product_urls = [(f"{base_url}?SKU={code.replace('.', '')}&ProductQuantity=20000", code) for code in stock_codes]

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

        if os.path.exists(OUTPUT_FILE):
            os.remove(OUTPUT_FILE)

        output_data = pd.DataFrame(results)
        # Move stockCode column to the leftmost position
        cols = output_data.columns.tolist()
        if "stockCode" in cols:
            cols.remove("stockCode")
            cols = ["stockCode"] + cols
            output_data = output_data[cols]
        output_data.to_excel(OUTPUT_FILE, index=False)
        print(f"✅ Results saved to {OUTPUT_FILE}")

        email = os.getenv("gmail_receiver_email_2")
        email_2 = os.getenv("gmail_receiver_email")
      
        try:
            send_mail_with_excel(email, OUTPUT_FILE)
            send_mail_with_excel(email_2, OUTPUT_FILE)

            print(f"📧 Email sent to {email} and {email_2}")
        except Exception as e:
            print(f"❌ Error sending email: {e}")

        # Send scrape finished email
        try:
            send_mail(
                informal_mail,
                subject="✅ Hafele Web Scraping Completed",
                body="The Hafele web scraping process has completed successfully. Results have been saved and sent to the recipients."
            )
        except Exception as e:
            print(f"❌ Error sending completion email: {e}")

        print(f"\n✅ Scraping complete. Process will exit now.\n")
    
    except Exception as e:
        # Send error email with exception message
        error_body = f"The Hafele web scraping process encountered an error:\n\nException: {str(e)}"
        try:
            send_mail(
                informal_mail,
                subject="❌ Hafele Web Scraping Failed",
                body=error_body
            )
        except Exception as email_error:
            print(f"❌ Error sending error email: {email_error}")
        
        print(f"❌ Error during scraping: {e}")
        raise
    finally:
        # Stop the refresh login thread
        stop_refreshing = True

if __name__ == "__main__":
    main()
