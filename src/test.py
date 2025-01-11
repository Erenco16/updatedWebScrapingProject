from selenium import webdriver

def test_chrome():
    options = webdriver.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--headless")  # Run in headless mode
    options.set_capability("platformName", "linux")  # Match platform from Grid status

    # Selenium Grid URL
    grid_url = "http://localhost:4444/wd/hub"

    print("Initializing WebDriver with Chrome...")
    driver = webdriver.Remote(command_executor=grid_url, options=options)
    print("Chrome WebDriver initialized successfully.")

    try:
        # Open a test website
        driver.get("https://www.example.com")
        print(f"Page title: {driver.title}")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        driver.quit()
        print("WebDriver session ended.")

if __name__ == "__main__":
    test_chrome()
