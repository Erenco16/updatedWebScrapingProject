"""
reporter.py  ── Post-process reporter

Queries the SQLite database, generates an Excel file, and sends
email notifications using the legacy mail logic from
scrape_all_products_main.

Data flow:
    SQLite → pandas DataFrame → Excel → Email attachment
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from dotenv import load_dotenv

from database import get_all_products, count_products
from src.send_mail import send_mail, send_mail_with_excel

load_dotenv()

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/app/data")


def generate_excel() -> str:
    """Read all products from SQLite and write an .xlsx file."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    rows = get_all_products()
    total = count_products()

    if not rows:
        print("⚠️ No products found in database.")
        return None

    df = pd.DataFrame(rows)
    # Drop internal id / scraped_at from final report for cleanliness
    drop_cols = ["id", "scraped_at", "is_group_product"]
    for col in drop_cols:
        if col in df.columns:
            df = df.drop(columns=[col])

    # Ensure stockCode is the leftmost column
    cols = df.columns.tolist()
    if "stock_code" in cols:
        cols.remove("stock_code")
        cols = ["stock_code"] + cols
        df = df[cols]

    today = str(date.today()).replace("-", "_")
    filename = f"{today}_Hafele_Guncel_Stoklar.xlsx"
    filepath = os.path.join(OUTPUT_DIR, filename)

    df.to_excel(filepath, index=False)
    print(f"✅ Excel generated: {filepath} ({total} rows)")
    return filepath


def send_notification_emails(excel_path: str):
    """Send Excel to primary recipients and plain-text status to informal_mail."""
    informal_mail = os.getenv("informal_mail")
    email_1 = os.getenv("informal_mail")
    # email_2 = os.getenv("gmail_receiver_email_2")
    total = count_products()

    # Send Excel attachments
    for recipient in (email_1):
        if recipient:
            try:
                send_mail_with_excel(recipient, excel_path)
            except Exception as e:
                print(f"❌ Failed to send Excel to {recipient}: {e}")

    # Send completion summary to informal_mail
    if informal_mail:
        try:
            body = (
                f"The Hafele web scraping process has completed successfully.\n\n"
                f"Total products scraped: {total}\n"
                f"Excel file: {os.path.basename(excel_path)}"
            )
            send_mail(
                informal_mail,
                subject="✅ Hafele Web Scraping Completed",
                body=body,
            )
        except Exception as e:
            print(f"❌ Failed to send completion email: {e}")


def main():
    print("=" * 60)
    print("📊 HAFELE REPORTER")
    print("=" * 60)

    total = count_products()
    print(f"📦 Products in database: {total}")

    if total == 0:
        print("⚠️ Nothing to report. Skipping Excel/email.")
        informal_mail = os.getenv("informal_mail")
        if informal_mail:
            send_mail(
                informal_mail,
                subject="⚠️ Hafele Web Scraping – No Data",
                body="The scraping process completed but no products were stored in the database.",
            )
        return

    excel_path = generate_excel()
    if excel_path:
        send_notification_emails(excel_path)
        print("\n✅ Reporter finished.")


if __name__ == "__main__":
    main()
