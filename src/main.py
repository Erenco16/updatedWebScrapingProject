import json
import requests
from src.login import handle_login


def save_cookies(driver, filename="cookies.json"):
    """
    Save cookies from the Selenium driver to a JSON file.
    """
    cookies = driver.get_cookies()
    with open(filename, "w") as file:
        json.dump(cookies, file)
    print("Cookies saved to file.")


def load_cookies(filename="cookies.json"):
    """
    Load cookies from a JSON file and return them as a dictionary formatted for `requests`.
    """
    with open(filename, "r") as file:
        selenium_cookies = json.load(file)

    cookies = {cookie['name']: cookie['value'] for cookie in selenium_cookies}
    return cookies


def make_authenticated_request(url, cookies, headers=None, params=None):
    """
    Make an authenticated request to a URL using cookies from Selenium.
    """
    session = requests.Session()
    session.cookies.update(cookies)

    response = session.post(url, headers=headers, params=params)

    if response.status_code == 200:
        print("Successfully accessed the page.")
        return response
    else:
        print(f"Failed to access page, status code: {response.status_code}")
        print(response.text)
        return None


def main():
    driver = handle_login()

    save_cookies(driver)

    driver.quit()

    cookies = load_cookies()

    url = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS?SKU=13593903&ProductQuantity=500000"
    headers = {
        "Accept": "text/html, */*; q=0.01",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-GB,en;q=0.9",
        "Cache-Control": "no-cache",
        "Content-Length": "0",
        "Origin": "https://www.hafele.com.tr",
        "Pragma": "no-cache",
        "Priority": "u=1, i",
        "Referer": "https://www.hafele.com.tr/tr/product/due-me-kulp-alueminyum-kolay-tutma-formlu/P-00854894/",
        "sec-ch-ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest"
    }
    params = {
        "SKU": "13593903",
        "ProductQuantity": "500000"
    }

    # Step 6: Make the authenticated request
    response = make_authenticated_request(url, cookies, headers=headers, params=params)

    # Step 7: Process the response
    if response:
        print("Response content:", response.text)  # Or response.json() if expecting JSON


if __name__ == '__main__':
    main()
