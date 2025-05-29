import os
import time
import pandas as pd
from scraper_main import run_scraper_once
from send_mail import send_mail_with_excel, send_mail_without_excel

LOCK_FILE = "/shared/hafele_login.lock"
DONE_FLAG = "/shared/done.flag"
OUTPUT_FILE = "/src/output/product_data_results.xlsx"
INPUT_FILE = "/src/input/product_codes.xlsx"

MAX_RETRIES = 3
retry_dict = {}
failed_codes = []

# Ensure old done flag is removed if it exists
if os.path.exists(DONE_FLAG):
    os.remove(DONE_FLAG)

# Load product codes
df_all = pd.read_excel(INPUT_FILE)
codes_to_scrape = df_all["stockCode"].astype(str).tolist()

master_df = pd.DataFrame()
scraped_codes = set()

send_mail_without_excel(
    "erenbasaran50@gmail.com",
    "Web scraping process started",
    f"{len(codes_to_scrape)} products will be scraped."
)

while True:
    remaining_codes = [code for code in codes_to_scrape if code not in scraped_codes and retry_dict.get(code, 0) < MAX_RETRIES]

    if not remaining_codes:
        print("✅ All products processed. Writing final file.")
        master_df.to_excel(OUTPUT_FILE, index=False)
        send_mail_with_excel("erenbasaran50@gmail.com", OUTPUT_FILE)

        if failed_codes:
            failed_log = "/src/output/failed_codes.txt"
            with open(failed_log, "w") as f:
                f.write("\n".join(failed_codes))
            print(f"⚠️ Some products failed. Logged to {failed_log}.")

        with open(DONE_FLAG, "w") as f:
            f.write("done")
        break

    next_code = remaining_codes[0]

    for attempt in range(1, MAX_RETRIES + 1):
        row_df = run_scraper_once(next_code)
        if row_df is not None and not row_df.empty:
            code_scraped = str(row_df.iloc[0]["stockCode"])
            if code_scraped not in scraped_codes:
                master_df = pd.concat([master_df, row_df], ignore_index=True)
                scraped_codes.add(code_scraped)
                print(f"✅ Scraped: {code_scraped}")
            break
        else:
            print(f"🔁 Retry {attempt}/{MAX_RETRIES} for {next_code}")
            retry_dict[next_code] = attempt
            time.sleep(2 ** attempt)  # Exponential backoff with 2s, 4s, 8s

    else:
        print(f"❌ Failed {next_code} after {MAX_RETRIES} attempts.")
        failed_codes.append(next_code)
