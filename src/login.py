from selenium import webdriver
from selenium.webdriver.common.by import By
import os
from dotenv import load_dotenv
import time
import pickle
import json

load_dotenv()


def handle_login():
    from selenium.webdriver.chrome.options import Options

    # Initialize Chrome driver with custom options
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")  # Avoid detection as a bot
    options.add_argument("--start-maximized")  # Start with a maximized window for consistent behavior

    # Load driver
    driver = webdriver.Chrome(options=options)

    # Open the website
    driver.get("https://www.hafele.com.tr/")

    time.sleep(5)

    # Get username and password from environment variables
    username = os.getenv("USERNAME")
    password = os.getenv("PASSWORD")

    # Close the initial warning page
    try:
        element = driver.find_element(By.XPATH,
                                      "//a[contains(@class, 'a-btn') and contains(@class, 't-btn') and contains(@class, 't-btn-secondary') and contains(@class, 'modal-link')]")
        driver.execute_script("arguments[0].click();", element)
    except Exception as e:
        print(f"Warning page close failed: {e}")

    # Handle login
    login_header = driver.find_element(By.ID, "headerLoginLinkAction")
    login_header.click()

    username_input = driver.find_element(By.ID, "ShopLoginForm_Login_headerItemLogin")
    password_input = driver.find_element(By.ID, "ShopLoginForm_Password_headerItemLogin")
    username_input.send_keys(username)
    password_input.send_keys(password)

    # Keep session open checkbox
    try:
        checkbox = driver.find_element(By.ID, "divShopLoginForm_RememberLogin_headerItemLogin")
        checkbox.click()
    except Exception as e:
        print(f"Checkbox click failed: {e}")

    time.sleep(2)

    # Login button click
    login_btn = driver.find_element(By.XPATH, "//button[@data-testid='ajaxAccountLoginFormBtn']")
    login_btn.click()
    time.sleep(10)

    # Add the user agent here:
    user_agent = os.getenv("USER_AGENT")

    # Save cookies after logging in
    try:
        with open("cookies.pkl", "wb") as file:
            print(driver.get_cookies())
            pickle.dump(driver.get_cookies(), file)
        # Create the user agent file
        with open("user_agent.txt", "w") as file:
            file.write(user_agent)
    except Exception as e:
        print(f"Failed to save cookies: {e}")

    # Save session information from localStorage
    try:
        session_info = driver.execute_script("return window.localStorage.getItem('sessionInfoData');")
        if session_info:
            # Parse and save sessionInfoData as JSON
            session_info_json = json.loads(session_info)
            with open("session_info.json", "w") as file:
                json.dump(session_info_json, file, indent=4)
                file.flush()  # Ensure the data is written to disk
                os.fsync(file.fileno())  # Force the OS to flush the file
            print(f"Session info saved: {session_info_json}")
        else:
            print("No sessionInfoData found in localStorage.")
    except Exception as e:
        print(f"Failed to save session info: {e}")

    return driver
