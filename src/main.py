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
from src.send_mail import send_mail_with_excel, send_mail
from src.scraper import retrieve_product_data

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
    """
    Main scraping workflow:
    1. Create single Selenium driver with retry
    2. Login using that driver
    3. Scrape all products using browser navigation
    4. Quit driver and cleanup
    """
    informal_mail = os.getenv("informal_mail")
    driver = None
    
    try:
        # Send scrape started email
        send_mail(
            informal_mail,
            subject="🚀 Hafele Web Scraping Started",
            body="The Hafele web scraping process has started. You will receive another email when it completes."
        )
    except Exception as e:
        logger.exception(f"❌ Error sending start email: {e}")
    
    try:
        # Create Selenium driver with robust retry (replaces /status polling)
        logger.debug("\n📱 Creating Selenium driver...\n")
        driver = make_driver()
        
        # Login using the driver
        logger.debug("\n🔐 Logging in...\n")
        login.handle_login(driver=driver)
        
        # Load product codes - pick 200 random ones
        df = pd.read_excel(INPUT_FILE)
        stock_codes = df["stockCode"].tolist()
        
        base_url = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"
        product_urls = [(f"{base_url}?SKU={code.replace('.', '')}&ProductQuantity=20000", code) for code in stock_codes]

        # Scrape all products using Selenium
        results = []
        for url, code in product_urls:
            try:
                logger.debug(f"Scraping data for stock code {code}...")
                result = retrieve_product_data(driver=driver, url=url, code=code)
                result["stockCode"] = code
                results.append(result)
            except Exception as e:
                logger.exception(f"Error processing stock code {code}: {e}")
                results.append({"stockCode": code, "stok_durumu": f"Error: {e}", "stock_amount": None})

        # Save results to Excel
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
        logger.debug(f"✅ Results saved to {OUTPUT_FILE}")

        email = os.getenv("gmail_receiver_email_2")
        email_2 = os.getenv("gmail_receiver_email")
      
        try:
            # send_mail_with_excel(email, OUTPUT_FILE)
            # send_mail_with_excel(email_2, OUTPUT_FILE)
            send_mail_with_excel(informal_mail, OUTPUT_FILE)
            logger.debug(f"📧 Email sent to {email} and {email_2}")
        except Exception as e:
            logger.debug(f"❌ Error sending email: {e}")

        # Send scrape finished email
        try:
            send_mail(
                informal_mail,
                subject="✅ Hafele Web Scraping Completed",
                body="The Hafele web scraping process has completed successfully. Results have been saved and sent to the recipients."
            )
        except Exception as e:
            logger.debug(f"❌ Error sending completion email: {e}")

        logger.debug(f"\n✅ Scraping complete. Process will exit now.\n")
    
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
            logger.debug(f"❌ Error sending error email: {email_error}")
        
        logger.debug(f"❌ Error during scraping: {e}")
        raise
    finally:
        # Always quit driver
        if driver:
            try:
                driver.quit()
                logger.debug("✅ Driver quit successfully")
            except Exception as e:
                logger.debug(f"⚠️ Error quitting driver: {e}")


if __name__ == "__main__":
    main()