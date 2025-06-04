import os
import sys
import pickle
import time
import pandas as pd
from dotenv import load_dotenv

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

# Load env
load_dotenv()

# Import project functions
from scraper.scraping_functions import retrieve_product_data
from scraper.send_mail import send_mail_without_excel, send_mail_with_excel

# Constants
BASE_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
INPUT_FILE = os.path.join(ROOT_DIR, "input", "product_codes.xlsx")
OUTPUT_FILE = os.path.join(ROOT_DIR, "output", "product_data_results.xlsx")
COOKIE_FILE = "/app/shared/cookies.pkl"
LOCK_FILE = "/app/shared/hafele_login.lock"
BASE_PRODUCT_URL = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"


def wait_for_initial_cookies():
    print("⏳ Waiting for cookies to be available...")
    while not os.path.exists(COOKIE_FILE):
        time.sleep(1)
    print("✅ Cookies file detected. Waiting 5 extra seconds...")
    time.sleep(5)


def wait_if_locked():
    while os.path.exists(LOCK_FILE):
        print("🔒 Login in progress, waiting...")
        time.sleep(120)


def load_cookies():
    if not os.path.exists(COOKIE_FILE):
        raise FileNotFoundError("❌ Cookies not found. Run login service first.")
    with open(COOKIE_FILE, "rb") as f:
        return pickle.load(f)


def process_product(code, cookies):
    wait_if_locked()
    url = f"{BASE_PRODUCT_URL}?SKU={code.replace('.', '')}&ProductQuantity=20000"
    try:
        data = retrieve_product_data(url, code, cookies)
        return {
            "stock_code": code,
            "kdv_haric_tavsiye_edilen_perakende_fiyat": data.get("kdv_haric_tavsiye_edilen_perakende_fiyat"),
            "kdv_haric_net_fiyat": data.get("kdv_haric_net_fiyat"),
            "kdv_haric_satis_fiyati": data.get("kdv_haric_satis_fiyati"),
            "stok_durumu": data.get("stok_durumu"),
            "stock_amount": data.get("stock_amount"),
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
        }


def main():
    wait_for_initial_cookies()
    cookies = load_cookies()

    print(f"📥 Reading product codes from {INPUT_FILE}")
    df_input = pd.read_excel(INPUT_FILE)
    codes = df_input.iloc[:, 0].dropna().astype(str).tolist()
    print(f"🔁 Scraping {len(codes)} products...")
    send_mail_without_excel("erenbasaran50@gmail.com")
    rows = []
    for i, code in enumerate(codes, 1):
        print(f"\n➡️ [{i}/{len(codes)}] Processing: {code}")
        row = process_product(code, cookies)
        rows.append(row)

    df_out = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    df_out.to_excel(OUTPUT_FILE, index=False)
    print(f"\n✅ Done. Saved results to {OUTPUT_FILE}")
    send_mail_with_excel("erenbasaran50@gmail.com", OUTPUT_FILE)

if __name__ == "__main__":
    main()
