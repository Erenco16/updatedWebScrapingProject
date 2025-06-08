import os
import sys
import pickle
import pandas as pd
from dotenv import load_dotenv
import threading
from datetime import datetime
import time

from exceptiongroup import catch

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

# Load env
load_dotenv()

# Import project functions
from scraper.scraping_functions import retrieve_product_data
from scraper.send_mail import send_mail_without_excel, send_mail_with_excel
from hafele_login.handle_login import handle_login
import random

# Constants
BASE_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
INPUT_FILE = os.path.join(ROOT_DIR, "input", "product_codes.xlsx")
OUTPUT_FILE = os.path.join(ROOT_DIR, "output", "product_data_results.xlsx")
COOKIE_FILE = os.path.join(ROOT_DIR, "shared", "cookies.pkl")
BASE_PRODUCT_URL = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"

# Global state
cookies = None
cookie_lock = threading.Lock()


def refresh_cookies():
    global cookies
    while True:
        print(f"🔁 [{datetime.now().strftime('%H:%M:%S')}] Refreshing cookies...")
        with cookie_lock:
            try:
                driver = handle_login()
                cookies = driver.get_cookies()
                driver.quit()
                with open(COOKIE_FILE, "wb") as f:
                    pickle.dump(cookies, f)
                print(f"✅ Cookies refreshed at {datetime.now().strftime('%H:%M:%S')}")
            except Exception as e:
                print(f"❌ Failed to refresh cookies: {e}")
        time.sleep(480)  # 8 minutes


def load_initial_cookies():
    global cookies
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, "rb") as f:
            cookies = pickle.load(f)
            print("✅ Initial cookies loaded from file.")
    else:
        print("⚠️ No cookie file found. Logging in initially...")
        driver = handle_login()
        cookies = driver.get_cookies()
        driver.quit()
        os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)
        with open(COOKIE_FILE, "wb") as f:
            pickle.dump(cookies, f)
        print("✅ Initial cookies fetched and saved.")

def parse_price(price_str):
    return float(price_str.replace(".", "").replace(",", "."))

def process_product(code):
    global cookies
    url = f"{BASE_PRODUCT_URL}?SKU={code.replace('.', '')}&ProductQuantity=20000"
    with cookie_lock:
        try:
            data = retrieve_product_data(url, code, cookies)
            return {
                "stock_code": code,
                "kdv_haric_tavsiye_edilen_perakende_fiyat": data.get("kdv_haric_tavsiye_edilen_perakende_fiyat"),
                "kdv_haric_net_fiyat": data.get("kdv_haric_net_fiyat"),
                "kdv_haric_satis_fiyati": data.get("kdv_haric_satis_fiyati"),
                "stok_durumu": data.get("stok_durumu"),
                "stock_amount": data.get("stock_amount"),
                "minimum_alis_fiyati": data.get("minimum_alis_fiyati"),
                "minimum_alis_carpi_kdv_haric_satis": parse_price(data.get("kdv_haric_satis_fiyati")) * int(data.get("minimum_alis_fiyati")),
            }
        except Exception as e:
            print(f"❌ Error processing product {code}: {e}")
            return {
                "stock_code": code,
                "kdv_haric_tavsiye_edilen_perakende_fiyat": None,
                "kdv_haric_net_fiyat": None,
                "kdv_haric_satis_fiyati": None,
                "stok_durumu": "HATA",
                "stock_amount": None,
                "minimum_alis_fiyati": None,
                "minimum_alis_carpi_kdv_haric_satis": None,
            }


def main():
    try:
        st = time.time()
        load_initial_cookies()

        # Start background thread for refreshing cookies
        threading.Thread(target=refresh_cookies, daemon=True).start()

        print(f"📥 Reading product codes from {INPUT_FILE}")
        df_input = pd.read_excel(INPUT_FILE)
        codes = df_input.iloc[:, 0].dropna().astype(str).tolist()
        print(f"🔁 Scraping {len(codes)} products...")
        informal_mail = os.getenv("gmail_receiver_email_3")
        send_mail_without_excel(informal_mail, content=f"{len(codes)} urunun web kazima islemi baslatildi.")

        rows = []
        for i, code in enumerate(codes, 1):
            print(f"\n➡️ [{i}/{len(codes)}] Processing: {code}")
            row = process_product(code)
            rows.append(row)

        df_out = pd.DataFrame(rows)
        df_out.to_excel(OUTPUT_FILE, index=False)
        print(f"\n✅ Done. Saved results to {OUTPUT_FILE}")
        send_mail_with_excel(os.getenv("gmail_receiver_email"), OUTPUT_FILE)
        send_mail_with_excel(os.getenv("gmail_receiver_email_2"), OUTPUT_FILE)
        send_mail_without_excel(informal_mail, content=f"{len(codes)} urunun web kazima islemi basariyla tamamlandi.")

        et = time.time()
        print(f"Time took to scrape {len(codes)} products: {round((et - st)/60, 2)} minutes.")

    except Exception as e:
        send_mail_without_excel(informal_mail, content=f"Web kazima islemi hata verdi. Hicbir urunun verisi edinelemedi. Hata: {e}")

if __name__ == "__main__":
    main()
