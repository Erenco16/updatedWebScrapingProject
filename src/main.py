"""
main.py
-------
Entry point only. Responsible for:
- Driver creation and login
- Loading input Excel
- Delegating to tab_pool and scraper
- Saving output Excel
- Sending notification emails
"""

import os
import pandas as pd
from dotenv import load_dotenv

from src import login
from src.selenium_client import make_driver
from src.tab_pool import open_tab_pool
from src.scraper import scrape_with_tab_pool, FETCH_FAILED
from src.send_mail import send_mail_with_excel, send_mail

from src.util.logger_util import CustomLogger

log_manager = CustomLogger(__name__, log_file="main-file.log")
logger = log_manager.get_logger()

load_dotenv()

BASE_DIR    = os.path.dirname(__file__)
INPUT_FILE  = os.path.join(BASE_DIR, "input",  "product_codes.xlsx")
OUTPUT_FILE = os.path.join(BASE_DIR, "output", "product_data_results.xlsx")

BASE_PRODUCT_URL = (
    "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY"
    "/ViewProduct-GetPriceAndAvailabilityInformationPDS"
)


def main():
    informal_mail = os.getenv("informal_mail")
    driver = None

    try:
        send_mail(
            informal_mail,
            subject="🚀 Hafele Web Scraping Started",
            body="Scraping started with 5-tab pool optimisation. Another email will follow on completion.",
        )
    except Exception as e:
        logger.exception(f"❌ Error sending start email: {e}")

    try:
        # ── Driver + login ────────────────────────────────────────────────────
        logger.info("\n📱 Creating Selenium driver...\n")
        driver = make_driver()

        logger.info("\n🔐 Logging in...\n")
        login.handle_login(driver=driver)

        # ── Capture cookies ───────────────────────────────────────────────────
        logger.info("\n🍪 Capturing login cookies...\n")
        cookies = driver.get_cookies()
        logger.info(f"✓ Captured {len(cookies)} cookies")

        # ── Open tab pool ─────────────────────────────────────────────────────
        tab_handles = open_tab_pool(
            driver,
            n_tabs=5,
            base_url="https://www.hafele.com.tr/",
            cookies=cookies,
        )

        # ── Load product codes ────────────────────────────────────────────────
        df          = pd.read_excel(INPUT_FILE)
        stock_codes = df["stockCode"].tolist()

        product_urls = [
            (f"{BASE_PRODUCT_URL}?SKU={code.replace('.', '')}&ProductQuantity=20000", code)
            for code in stock_codes
        ]

        # ── Scrape ────────────────────────────────────────────────────────────
        results = scrape_with_tab_pool(
            driver=driver,
            handles=tab_handles,
            product_urls=product_urls,
        )

        # ── Save to Excel ─────────────────────────────────────────────────────
        if os.path.exists(OUTPUT_FILE):
            os.remove(OUTPUT_FILE)

        output_data = pd.DataFrame(results)
        if "stockCode" in output_data.columns:
            cols = ["stockCode"] + [c for c in output_data.columns if c != "stockCode"]
            output_data = output_data[cols]

        output_data.to_excel(OUTPUT_FILE, index=False)
        logger.info(f"✅ Results saved to {OUTPUT_FILE}")

        # ── Send results email ────────────────────────────────────────────────
        failed_count = int((output_data["stok_durumu"] == FETCH_FAILED).sum())
        total_count  = len(output_data)

        # for recipient in [os.getenv("gmail_receiver_email_2"), os.getenv("gmail_receiver_email")]:
        #     try:
        #         send_mail_with_excel(recipient, OUTPUT_FILE)
        #         logger.info(f"📧 Email sent to {recipient}")
        #     except Exception as e:
        #         logger.exception(f"❌ Failed to send email to {recipient}: {e}")

        send_mail_with_excel(informal_mail, OUTPUT_FILE)
        
        try:
            send_mail(
                informal_mail,
                subject="✅ Hafele Web Scraping Completed",
                body=(
                    f"Scraping completed.\n\n"
                    f"Total products : {total_count}\n"
                    f"Permanent fails: {failed_count}\n\n"
                    f"Failures are marked '{FETCH_FAILED}' in the Excel file."
                ),
            )
        except Exception as e:
            logger.exception(f"❌ Error sending completion email: {e}")

    except Exception as e:
        try:
            send_mail(
                informal_mail,
                subject="❌ Hafele Web Scraping Failed",
                body=f"Scraping failed.\n\nException: {e}",
            )
        except Exception:
            pass
        logger.exception(f"❌ Fatal error: {e}")
        raise

    finally:
        if driver:
            try:
                driver.quit()
                logger.info("✅ Driver quit")
            except Exception as e:
                logger.exception(f"⚠️ Error quitting driver: {e}")


if __name__ == "__main__":
    main()