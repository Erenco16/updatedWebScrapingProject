import os
import time
import pandas as pd
from scraper_main import run_scraper_once
from send_mail import send_mail_with_excel, send_mail_without_excel

LOCK_FILE = "/shared/login.lock"
DONE_FLAG = "/shared/done.flag"
OUTPUT_FILE = "/src/output/product_data_results.xlsx"
INPUT_FILE = "/src/input/product_codes.xlsx"

def wait_for_login():
    while os.path.exists(LOCK_FILE):
        print("⏳ Waiting for login to finish...")
        time.sleep(10)

# Load and sample ONCE
df_all = pd.read_excel(INPUT_FILE)
df_sample = df_all.sample(n=100, random_state=42)
codes_to_scrape = df_sample["stockCode"].astype(str).tolist()

master_df = pd.DataFrame()
scraped_codes = set()

print("🚀 Scraper loop started with 100 random products")
send_mail_without_excel("erenbasaran50@gmail.com", "Web scraping process started", f"{len(codes_to_scrape)} amount of products are going to be scraped.")
while True:
    wait_for_login()

    remaining_codes = [code for code in codes_to_scrape if code not in scraped_codes]

    if not remaining_codes:
        print("✅ All sampled products scraped. Writing final file.")
        master_df = master_df[master_df.columns[::-1]]
        master_df.to_excel(OUTPUT_FILE, index=False)
        send_mail_with_excel("erenbasaran50@gmail.com", OUTPUT_FILE)
        with open(DONE_FLAG, "w") as f:
            f.write("done")
        break

    next_code = remaining_codes[0]
    row_df = run_scraper_once(next_code)  # pass just one code
    if row_df is not None and not row_df.empty:
        code_scraped = str(row_df.iloc[0]["stockCode"])
        if code_scraped not in scraped_codes:
            master_df = pd.concat([master_df, row_df], ignore_index=True)
            scraped_codes.add(code_scraped)
            print(f"✅ Scraped: {code_scraped}")
        else:
            print(f"⚠️ Already scraped: {code_scraped}")
    time.sleep(2)
