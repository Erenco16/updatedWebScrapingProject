import os
import time
import requests
import zipfile
from datetime import datetime
from dotenv import load_dotenv

# Selenium helpers for interactive Datanorm request
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from src import login
from src import main as main_module
from src.send_mail import send_mail
import time

from src.input import get_all_products

load_dotenv()

BASE_DIR = os.path.dirname(__file__)
ATTACHMENTS_DIR = os.path.join(BASE_DIR, "attachments")
DATANORM_URL = (
    "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewDatanormDownload-View"
)


def ensure_cookies():
    """Ensure cookies.pkl exists and is valid; if not, perform login to create it."""
    informal_mail = os.getenv("informal_mail")

    if main_module.is_cookie_valid(main_module.COOKIE_FILE, main_module.COOKIE_EXPIRY):
        return main_module.load_cookies(main_module.COOKIE_FILE)

    # Perform login to refresh/create cookies
    try:
        driver = login.handle_login()
        driver.quit()
    except Exception as e:
        send_mail(
            informal_mail,
            subject="❌ Hafele Datanorm Login Failed",
            body=f"Login failed while preparing Datanorm download: {e}",
        )
        raise

    if os.path.exists(main_module.COOKIE_FILE):
        cookies = main_module.load_cookies(main_module.COOKIE_FILE)
        if cookies:
            return cookies
        else:
            send_mail(
                informal_mail,
                subject="❌ Hafele Datanorm Login Failed",
                body="Login completed but cookies are empty. Aborting Datanorm download.",
            )
            raise Exception("Cookies empty after login")
    else:
        send_mail(
            informal_mail,
            subject="❌ Hafele Datanorm Login Failed",
            body="Login attempted but cookies file was not created.",
        )
        raise Exception("Cookies file not found after login")


def download_datanorm(cookies, dest_dir=ATTACHMENTS_DIR, retries=3):
    """Download the Datanorm file using session cookies. Returns saved file path."""
    if isinstance(cookies, list):
        cookies = {c["name"]: c["value"] for c in cookies}

    os.makedirs(dest_dir, exist_ok=True)

    for attempt in range(retries):
        try:
            headers = main_module.get_random_headers()
            print(f"Requesting Datanorm URL: {DATANORM_URL}")
            response = requests.get(DATANORM_URL, headers=headers, cookies=cookies, timeout=60, stream=True)

            if response.status_code != 200:
                print(f"Datanorm request failed with status {response.status_code}. Retrying...")
                time.sleep(2 ** attempt)
                continue

            content_type = response.headers.get("Content-Type", "")
            content_disposition = response.headers.get("Content-Disposition", "")

            # Determine filename
            filename = None
            if "filename=" in content_disposition:
                filename = content_disposition.split("filename=")[-1].strip().strip('"')
            else:
                ext = ".zip" if "zip" in content_type else (
                    ".xlsx" if "spreadsheetml" in content_type or "excel" in content_type else ""
                )
                filename = f"datanorm_{int(time.time())}{ext}"

            file_path = os.path.join(dest_dir, filename)
            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            # If zip, extract and try to return the first spreadsheet found
            if file_path.lower().endswith(".zip"):
                extract_dir = os.path.join(dest_dir, f"extracted_{int(time.time())}")
                os.makedirs(extract_dir, exist_ok=True)
                try:
                    with zipfile.ZipFile(file_path, "r") as zf:
                        zf.extractall(extract_dir)
                    for root, _, files in os.walk(extract_dir):
                        for fname in files:
                            if fname.lower().endswith((".xls", ".xlsx")):
                                return os.path.join(root, fname)
                    # No spreadsheet found; return the zip
                    return file_path
                except zipfile.BadZipFile:
                    # Not a valid zip; return what we have
                    return file_path

            return file_path
        except requests.RequestException as e:
            print(f"Datanorm download request error: {e}. Retrying...")
            time.sleep(2 ** attempt)

    raise Exception("Failed to download Datanorm file after retries")


def download_datanorm_via_selenium(email_to_send="erenbasaran2002@gmail.com", timeout=30):
    """Use Selenium to open the Datanorm page, set options, provide email, and submit the request.

    Returns a dict with the result info (e.g., {'status': 'requested'}) or raises on failure.
    """
    informal_mail = os.getenv("informal_mail")
    driver = None
    try:
        driver = login.handle_login()
        # Navigate to Datanorm page
        driver.get(DATANORM_URL)

        wait = WebDriverWait(driver, timeout)
        wait.until(EC.presence_of_element_located((By.ID, "DatanormDownload_ArticleDataALL")))
        
        # Click article data ALL radio
        radio_article = wait.until(EC.element_to_be_clickable((By.ID, "DatanormDownload_ArticleDataALL")))
        driver.execute_script("arguments[0].click();", radio_article)

        # Click price type UVPE radio
        radio_price = wait.until(EC.element_to_be_clickable((By.ID, "DatanormDownload_PriceTypeUVPE")))
        driver.execute_script("arguments[0].click();", radio_price)

        # Click format EXCEL radio
        radio_format = wait.until(EC.element_to_be_clickable((By.ID, "DatanormDownload_FormatEXCEL")))
        driver.execute_script("arguments[0].click();", radio_format)

        # Fill email field
        email_field = wait.until(EC.presence_of_element_located((By.ID, "DatanormDownload_Email")))
        email_field.clear()
        email_field.send_keys(email_to_send)

        # Click download/request button
        download_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='DownloadArticleData']")))
        driver.execute_script("arguments[0].click();", download_btn)

        # Wait briefly for any confirmation / success message (best-effort)
        time.sleep(3)

        # Optionally, look for a success message or dialog; if none found, assume requested
        return {"status": "requested", "email": email_to_send}
    except Exception as e:
        # Notify and re-raise
        send_mail(informal_mail, subject="❌ Hafele Datanorm Request Failed", body=str(e))
        raise
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def run_send_product_code_mail():
    informal_mail = os.getenv("informal_mail")
    try:
        # Use Selenium-driven request for Datanorm
        result = download_datanorm_via_selenium()
        if result.get("status") == "requested":
            # Success: do not send success emails per request; just log
            print(f"✅ Datanorm requested for {result.get('email')}")
        else:
            # Failure: notify recipients
            send_mail(informal_mail, subject="❌ Datanorm Request Failed", body=str(result))
    except Exception as e:
        # On exception, notify and re-raise
        send_mail(informal_mail, subject="❌ Hafele Datanorm Failed", body=str(e))
        raise


if __name__ == "__main__":
    run_send_product_code_mail()
    time.sleep(1200)
    get_all_products.download_zip_attachment()
    get_all_products.update_product_codes_from_latest_attachment()