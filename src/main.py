import time
from bs4 import BeautifulSoup as bs4
import pickle
from selenium.webdriver.common.by import By
from src.login import handle_login


def refresh_driver(driver):
    # Navigate to the correct domain
    driver.get("https://www.hafele.com.tr")  # Use the domain of your cookies

    # Load cookies
    with open("cookies.pkl", "rb") as file:
        cookies = pickle.load(file)

    for cookie in cookies:
        try:
            # Remove incompatible or unnecessary attributes
            cookie.pop("sameSite", None)  # Remove `sameSite` if incompatible

            # Ensure domain matches the current domain
            if "www.hafele.com.tr" in driver.current_url:
                cookie["domain"] = "www.hafele.com.tr"

            # Skip cookies with empty values
            if not cookie["value"]:
                print(f"Skipping cookie with empty value: {cookie['name']}")
                continue

            # Add cookie to the browser
            driver.add_cookie(cookie)
        except Exception as e:
            print(f"Error adding cookie: {cookie}\n{e}")

    # Refresh the browser to apply cookies
    driver.refresh()


def get_product_info(driver, url):
    refresh_driver(driver)
    driver.get(url)
    stock_input = driver.find_element(By.ID, "ConditionConfiguration_pds_quantity_1")
    stock_input.send_keys("500.000")
    time.sleep(2)
    page_html = driver.page_source
    page_soup  = bs4(page_html, "html.parser")
    price = page_soup.find("span", {"class": "price"}).text
    stock_table = page_soup.find("table", {"class": "RequestedPackageTable productDataTable table table-bordered"})
    row = stock_table.find_all("tr")[1]
    stock_amount = row.find_all("td")[0].text
    return price, stock_amount

def main():
    driver = handle_login()
    product_url = "https://www.hafele.com.tr/tr/product/aksl-kulp-fermo-zamak/10001220/?MasterSKU=P-01956795"
    print(f"Info: {get_product_info(driver, product_url)}")
    driver.quit()


if __name__ == '__main__':
    main()
