import unittest
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
import pickle
import os
import time

# Import functions from your main script
from main import (
    handle_login_with_retry,
    load_cookies,
    retrieve_product_data,
    extract_price_info,
    does_product_exist,
    is_cookie_valid,
    retrieve_qty_available,
    handle_singular_product,
    handle_group_product,
    retrieve_singular_stock,
)


class TestScraping(unittest.TestCase):
    def setUp(self):
        """Set up test data and environment."""
        self.cookie_file = "test_cookies.pkl"
        self.mock_cookies = [{"name": "session", "value": "test_session"}]
        self.test_html = '''
        <div id="productDetails">
            <tr id="productPriceInformation">
                <span class="price">1.255,36 TL</span>
                <span class="price">1.883,04 TL</span>
                <span class="price">1.757,50 TL</span>
            </tr>
            <span class="availability-flag">stokta mevcut</span>
            <span class="qty-available">230</span>
        </div>
        '''
        # Clean up existing cookie files
        if os.path.exists(self.cookie_file):
            os.remove(self.cookie_file)

    def tearDown(self):
        """Clean up after tests."""
        if os.path.exists(self.cookie_file):
            os.remove(self.cookie_file)

    @patch("login.handle_login")
    def test_handle_login_with_retry(self, mock_handle_login):
        """Test login with retry mechanism."""
        mock_driver = MagicMock()
        mock_driver.quit = MagicMock()
        mock_handle_login.return_value = mock_driver

        # Test a successful login
        handle_login_with_retry()
        mock_handle_login.assert_called_once()
        mock_driver.quit.assert_called_once()

    def test_load_cookies(self):
        """Test loading cookies from file."""
        # Save test cookies
        with open(self.cookie_file, "wb") as f:
            pickle.dump(self.mock_cookies, f)

        # Load cookies and verify content
        cookies = load_cookies(self.cookie_file)
        expected_cookies = {cookie["name"]: cookie["value"] for cookie in self.mock_cookies}
        self.assertEqual(cookies, expected_cookies)

    @patch("os.path.exists")
    @patch("os.path.getmtime")
    def test_is_cookie_valid(self, mock_getmtime, mock_exists):
        """Test cookie validity check."""
        mock_exists.return_value = True
        mock_getmtime.return_value = time.time() - 300  # Modified 5 minutes ago

        # Test that cookies are valid within expiry time
        self.assertTrue(is_cookie_valid(self.cookie_file, 600))

        # Test that cookies are invalid after expiry time
        mock_getmtime.return_value = time.time() - 700
        self.assertFalse(is_cookie_valid(self.cookie_file, 600))

    @patch("requests.get")
    @patch("main.load_cookies")
    def test_retrieve_product_data(self, mock_load_cookies, mock_get):
        """Test product data retrieval including retries."""
        mock_cookies = {"session": "test_session"}
        mock_load_cookies.return_value = mock_cookies

        # Mock successful HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = self.test_html
        mock_get.return_value = mock_response

        url = "http://test_url"
        result = retrieve_product_data(url, mock_cookies)

        # Verify product data is correctly parsed
        self.assertEqual(result["stok_durumu"], "stokta mevcut")
        self.assertEqual(result["stock_amount"], 230)
        self.assertEqual(result["kdv_haric_satis_fiyati"], "1.883,04 TL")

    def test_extract_price_info(self):
        """Test that price information is correctly extracted."""
        soup = BeautifulSoup(self.test_html, "html.parser")
        prices = extract_price_info(soup)
        self.assertEqual(prices["kdv_haric_net_fiyat"], "1.255,36 TL")
        self.assertEqual(prices["kdv_haric_satis_fiyati"], "1.883,04 TL")
        self.assertEqual(prices["kdv_haric_tavsiye_edilen_perakende_fiyat"], "1.757,50 TL")

    def test_does_product_exist(self):
        """Test if product existence is correctly identified."""
        soup = BeautifulSoup(self.test_html, "html.parser")
        self.assertTrue(does_product_exist(soup))

        # Test with an invalid HTML (no product table)
        invalid_html = "<html></html>"
        soup = BeautifulSoup(invalid_html, "html.parser")
        self.assertFalse(does_product_exist(soup))

    @patch("requests.get")
    def test_retrieve_qty_available(self, mock_get):
        """Test quantity retrieval with retries."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = self.test_html
        mock_get.return_value = mock_response

        headers = {"User-Agent": "Mozilla/5.0"}
        cookies = {"session": "test_session"}
        url = "http://test_url"

        qty_available = retrieve_qty_available(url, cookies)
        self.assertEqual(qty_available, 230)

    def test_handle_singular_product(self):
        """Test handling singular products from BeautifulSoup data."""
        soup = BeautifulSoup(self.test_html, "html.parser")
        result = handle_singular_product(soup)

        # Validate results
        self.assertEqual(result["stok_durumu"], "stokta mevcut")
        self.assertEqual(result["stock_amount"], 230)
        self.assertEqual(result["kdv_haric_satis_fiyati"], "1.883,04 TL")

    @patch("requests.get")
    def test_retrieve_singular_stock(self, mock_get):
        """Test retrieving stock for a singular product."""
        # Mock successful response with stock available
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = self.test_html
        mock_get.return_value = mock_response

        url = "http://test_url"
        cookies = {"session": "test_session"}
        stock = retrieve_singular_stock(url, cookies)
        self.assertEqual(stock, 230)

        # Test unavailable stock
        test_html_no_stock = '''
        <div id="productDetails">
            <span class="availability-flag">stokta mevcut değil</span>
        </div>
        '''
        mock_response.text = test_html_no_stock
        stock = retrieve_singular_stock(url, cookies)
        self.assertEqual(stock, 0)

    @patch("requests.get")
    def test_handle_group_product(self, mock_get):
        """Test group product handling and stock aggregation."""
        # Mock response for sub-product requests
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = self.test_html
        mock_get.return_value = mock_response

        soup = BeautifulSoup(self.test_html, "html.parser")
        cookies = {"session": "test_session"}

        result = handle_group_product(soup, cookies)
        self.assertEqual(result["stok_durumu"], "set urun")
        self.assertEqual(result["stock_amount"], 230)


if __name__ == "__main__":
    unittest.main()
