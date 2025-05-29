import os
import pickle
import pandas as pd
from dotenv import load_dotenv
from scraping_functions import retrieve_product_data, is_cookie_valid  # update the path if needed
import time


# Load environment variables
load_dotenv()
LOCK_FILE = "/shared/hafele_login.lock"
INPUT_FILE = "/src/input/product_codes.xlsx"
OUTPUT_FILE = "/src/output/product_data_results.xlsx"
COOKIE_FILE = "/shared/cookies.pkl"

def load_cookies():
    with open(COOKIE_FILE, "rb") as f:
        cookies = pickle.load(f)
    return {cookie["name"]: cookie["value"] for cookie in cookies}

def get_remaining_product_count():
    if not os.path.exists(INPUT_FILE):
        return 0
    df_all = pd.read_excel(INPUT_FILE)
    if os.path.exists(OUTPUT_FILE):
        df_done = pd.read_excel(OUTPUT_FILE)
        remaining = df_all[~df_all['stockCode'].isin(df_done['stockCode'])]
        return len(remaining)
    return len(df_all)

def wait_for_login():
    while os.path.exists(LOCK_FILE):
        print("⏳ Waiting for hafele_login to finish...")
        time.sleep(10)


def run_scraper_once(code):
    """Scrape a single product code and return its row."""

    url = f"https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS?SKU={code.replace('.', '')}&ProductQuantity=20000"

    try:
        if not is_cookie_valid(cookie_file=COOKIE_FILE, expiry_time=600):
            print("⚠️ Cookie expired. Waiting for login refresh.")
            wait_for_login()

        print(f"🔍 Scraping product {code} ...")
        cookies = load_cookies()
        result = retrieve_product_data(url=url, code=code, cookie_information=cookies)
        result["stockCode"] = code
        return pd.DataFrame([result])
    except Exception as e:
        print(f"❌ Error scraping {code}: {e}")
        return pd.DataFrame([{
            "stockCode": code,
            "stok_durumu": f"Error: {e}",
            "stock_amount": None,
            "kdv_haric_tavsiye_edilen_perakende_fiyat": None,
            "kdv_haric_net_fiyat": None,
            "kdv_haric_satis_fiyati": None
        }])


