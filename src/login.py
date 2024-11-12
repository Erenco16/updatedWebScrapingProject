from selenium import webdriver
from selenium.webdriver.common.by import By
import os
from dotenv import load_dotenv
import time

load_dotenv()

def handle_login():
    driver = webdriver.Chrome()

    driver.get("https://www.hafele.com.tr/")

    time.sleep(5)

    username = os.getenv("USERNAME")
    password = os.getenv("PASSWORD")

    # close the initial warning page
    element = driver.find_element(By.XPATH,
                                  "//a[contains(@class, 'a-btn') and contains(@class, 't-btn') and contains(@class, 't-btn-secondary') and contains(@class, 'modal-link')]")
    driver.execute_script("arguments[0].click();", element)

    # login handling
    login_header = driver.find_element(By.ID, "headerLoginLinkAction")
    login_header.click()

    username_input = driver.find_element(By.ID, "ShopLoginForm_Login_headerItemLogin")
    password_input = driver.find_element(By.ID, "ShopLoginForm_Password_headerItemLogin")
    username_input.send_keys(username)
    password_input.send_keys(password)

    # keep my session open check box
    checkbox = driver.find_element(By.ID, "divShopLoginForm_RememberLogin_headerItemLogin")

    checkbox.click()

    time.sleep(5)

    # and now we are logging in
    login_btn = driver.find_element(By.XPATH, "//button[@data-testid='ajaxAccountLoginFormBtn']")
    login_btn.click()

    return driver

if __name__ == '__main__':
    main()