from selenium import webdriver
from selenium.webdriver.common.by import By
import os
from dotenv import load_dotenv
import time
import pickle
import json
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

load_dotenv()

def handle_login():
    """Perform login using Selenium and save cookies."""
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"user-agent={os.getenv('USER_AGENT', 'Mozilla/5.0')}")

    # Selenium Grid Hub URL
    selenium_hub_url = os.getenv("GRID_URL", "http://selenium-hub:4444/wd/hub")

    # Initialize the Remote WebDriver
    driver = webdriver.Remote(
        command_executor=selenium_hub_url,
        options=options
    )

    wait = WebDriverWait(driver, 15)

    driver.get("https://www.hafele.com.tr/")
    time.sleep(3)

    username = os.getenv("hafele_username")
    password = os.getenv("hafele_password")

    try:
        # Step 1: Click the accept button (if it's there)
        cookie_btn = wait.until(EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler")))
        cookie_btn.click()

        # Step 2: Wait for the dark overlay to disappear (invisible or detached from DOM)
        wait.until(EC.invisibility_of_element_located((By.CLASS_NAME, "onetrust-pc-dark-filter")))
    except TimeoutException:
        try:
            driver.execute_script("""
                let overlay = document.querySelector('.onetrust-pc-dark-filter');
                if (overlay) {
                    overlay.style.display = 'none';
                    overlay.remove();  // try to fully remove it
                }
            """)
        except Exception as e:
            print(f"Failed to remove overlay manually: {e}")
    except Exception as e:
        print(f"Cookie banner handling failed or not present: {e}")

    # Step 2: Close initial modal if "Stay Here" is visible
    try:
        stay_here_btn = wait.until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//a[contains(@class, 'modal-link') and normalize-space(text())='Stay Here']"
            ))
        )
        driver.execute_script("arguments[0].click();", stay_here_btn)
        time.sleep(1)
    except Exception as e:
        print(f"No 'Stay Here' modal found or already handled: {e}")

    # Step 3: Click on the login button in header
    login_header = wait.until(EC.element_to_be_clickable((By.ID, "headerLoginLinkAction")))
    driver.execute_script("arguments[0].click();", login_header)

    # Step 4: Fill in login form
    username_input = wait.until(EC.visibility_of_element_located((By.ID, "ShopLoginForm_Login_headerItemLogin")))
    password_input = wait.until(EC.visibility_of_element_located((By.ID, "ShopLoginForm_Password_headerItemLogin")))
    username_input.send_keys(username)
    password_input.send_keys(password)

    # Step 5: Click 'Remember Me' checkbox (if found)
    try:
        checkbox = driver.find_element(By.ID, "divShopLoginForm_RememberLogin_headerItemLogin")
        checkbox.click()
    except Exception:
        pass

    # Final check for cookie accept button before login click
    try:
        final_cookie_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
        )
        final_cookie_btn.click()
        # Wait for overlay to vanish again if needed
        WebDriverWait(driver, 5).until(
            EC.invisibility_of_element_located((By.CLASS_NAME, "onetrust-pc-dark-filter"))
        )
    except Exception as e:
        print("No final cookie prompt appeared.")

    # Always try to remove OneTrust overlay, just in case it's still present
    try:
        driver.execute_script("""
            let overlay = document.querySelector('.onetrust-pc-dark-filter');
            if (overlay) {
                overlay.style.display = 'none';
                overlay.style.visibility = 'hidden';
                overlay.style.pointerEvents = 'none';
                overlay.remove();
                console.log('OneTrust overlay force-removed.');
            }
        """)
    except Exception as e:
        print(f"Overlay removal (final attempt) failed: {e}")

    # Step 6: Submit the login form
    login_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='ajaxAccountLoginFormBtn']")))
    login_btn.click()

    time.sleep(10)

    # Step 7: Save cookies to file
    with open("cookies.pkl", "wb") as file:
        pickle.dump(driver.get_cookies(), file)

    # Step 8: Save sessionInfoData from localStorage (if exists)
    try:
        session_info = driver.execute_script("return window.localStorage.getItem('sessionInfoData');")
        if session_info:
            session_info_json = json.loads(session_info)
            with open("session_info.json", "w") as file:
                json.dump(session_info_json, file, indent=4)
            print("Session info saved.")
    except Exception as e:
        print(f"Session info not found or failed to save: {e}")

    return driver
