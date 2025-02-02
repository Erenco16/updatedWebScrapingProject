import unittest
import requests
import pickle
import os
from bs4 import BeautifulSoup
import pandas as pd

# Import functions from your main script
from src.main import (
    handle_login_with_retry,
    retrieve_product_data,
    extract_price_info,
    does_product_exist,
    retrieve_qty_available,
    handle_singular_product,
)

class TestScrapingWithDynamicCookies(unittest.TestCase):
    def setUp(self):
        """Set up test environment and retrieve fresh cookies."""
        current_directory = os.path.dirname(__file__)
        error_product_codes = os.path.join(current_directory, 'error_file.xlsx')
        error_df = pd.read_excel(error_product_codes)
        self.cookie_file = "cookies.pkl"  # Ensure this is the correct file updated by handle_login_with_retry()
        self.test_product_code = error_df['product_code'].sample(1).iloc[0]  # random product code that returned with an error
        base_url = "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"
        self.test_url = f"{base_url}?SKU={self.test_product_code.replace('.', '')}&ProductQuantity=50000"

        print(f"Product code to be tested: {self.test_product_code}")
        # Step 1: Login to refresh cookies
        handle_login_with_retry()

        # Step 2: Load the latest cookies
        self.cookies = self.load_latest_cookies()

        # Step 3: Fetch the real product page HTML
        self.test_html = self.fetch_real_product_page(self.test_url)

    def load_latest_cookies(self):
        """Load updated cookies after login."""
        if os.path.exists(self.cookie_file):
            with open(self.cookie_file, "rb") as f:
                raw_cookies = pickle.load(f)
                return {cookie["name"]: cookie["value"] for cookie in raw_cookies}
        else:
            self.skipTest("Skipping test: No cookies file found after login attempt.")

    def fetch_real_product_page(self, url):
        """Fetch the actual product page using the updated cookies."""
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, cookies=self.cookies)

        if response.status_code == 200:
            return response.text
        else:
            self.skipTest(f"Skipping test: Product page not accessible ({response.status_code}).")

    def test_retrieve_product_data(self):
        """Test product data retrieval using real product codes and updated cookies."""
        result = retrieve_product_data(self.test_url, self.cookies)

        # Validate the structure
        self.assertIn("stok_durumu", result)
        self.assertIn("stock_amount", result)
        self.assertIn("kdv_haric_satis_fiyati", result)

    def test_extract_price_info(self):
        """Test extracting price information from real product HTML."""
        soup = BeautifulSoup(self.test_html, "html.parser")
        prices = extract_price_info(soup)

        # Validate expected price keys exist
        self.assertIn("kdv_haric_net_fiyat", prices)
        self.assertIn("kdv_haric_satis_fiyati", prices)
        self.assertIn("kdv_haric_tavsiye_edilen_perakende_fiyat", prices)

    def test_does_product_exist(self):
        """Test if a product exists using real product code and updated cookies."""
        soup = BeautifulSoup(self.test_html, "html.parser")
        self.assertTrue(does_product_exist(soup))

    def test_retrieve_qty_available(self):
        """Test retrieving stock quantity with a real product code and updated cookies."""
        qty_available = retrieve_qty_available(self.test_url, self.cookies)

        self.assertIsInstance(qty_available, int)  # Should return an integer stock count

    def test_handle_singular_product(self):
        """Test handling of a singular product using real data and updated cookies."""
        soup = BeautifulSoup(self.test_html, "html.parser")
        result = handle_singular_product(soup)

        # Validate expected keys exist
        self.assertIn("stok_durumu", result)
        self.assertIn("stock_amount", result)
        self.assertIn("kdv_haric_satis_fiyati", result)


if __name__ == "__main__":
    unittest.main()