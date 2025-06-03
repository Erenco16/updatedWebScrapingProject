import os
import sys
import pickle
import requests
import pandas as pd
from dotenv import load_dotenv

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

# Load env
load_dotenv()
os.environ["GRID_URL"] = "http://localhost:4444/wd/hub"

# Import project functions
from scraper.scraping_functions import (
    retrieve_product_data,
    does_product_exist
)
from hafele_login.handle_login import handle_login

# Constants
BASE_DIR = os.path.dirname(__file__)
INPUT_FILE = os.path.join(BASE_DIR, "input", "product_codes.xlsx")
OUTPUT_FILE = os.path.join(BASE_DIR, "output", "product_data_results.xlsx")
COOKIE_FILE = os.path.join(BASE_DIR, "cookies.pkl")
BASE_PRODUCT_URL = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"


def load_cookies():
    if not os.path.exists("/app/shared/cookies.pkl"):
        raise FileNotFoundError("❌ Cookies not found. Run login service first.")

    with open("/app/shared/cookies.pkl", "rb") as f:
        return pickle.load(f)



def fetch_product_page(url, cookies):
    session = requests.Session()
    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'])

    headers = {"User-Agent": "Mozilla/5.0"}
    response = session.get(url, headers=headers, timeout=30)

    return response.text if response.status_code == 200 else None


def process_product(code, cookies):
    result = {
        "code": code,
        "url": None,
        "metadata": {},
        "exists": None,
        "errors": {}
    }

    try:
        url = f"{BASE_PRODUCT_URL}?SKU={code.replace('.', '')}&ProductQuantity=20000"
        result["url"] = url
        data = retrieve_product_data(url, code, cookies)
        result["metadata"] = data
        result["exists"] = does_product_exist(code, cookies)
    except Exception as e:
        result["errors"]["scrape"] = str(e)

    return result


def main():
    cookies = load_cookies()
    if not cookies:
        print("❌ Could not retrieve cookies. Exiting.")
        return

    print(f"📥 Reading product codes from {INPUT_FILE}")
    df_input = pd.read_excel(INPUT_FILE)
    # codes = df_input.iloc[:, 0].dropna().astype(str).tolist()
    codes = ["803.30.500"]
    print(f"🔁 Scraping {len(codes)} products...")

    results = []
    for i, code in enumerate(codes, 1):
        print(f"\n➡️ [{i}/{len(codes)}] Processing code: {code}")
        result = process_product(code, cookies)
        results.append(result)

    df_results = pd.DataFrame(results)
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    df_results.to_excel(OUTPUT_FILE, index=False)
    print(f"\n✅ All done. Results saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
