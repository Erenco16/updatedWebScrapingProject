import os
import sys
import pickle
import pytest
from unittest.mock import patch, MagicMock

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from core.main import (
    load_initial_cookies,
    process_product,
    get_cookie_snapshot,
    parse_price,
)

from scraper.scraping_functions import does_product_exist

# ---------- FIXTURES ----------

@pytest.fixture(scope="module")
def sample_cookies():
    return [{'name': 'session', 'value': 'abc', 'domain': 'www.hafele.com.tr'}]

@pytest.fixture(scope="module")
def sample_product_code():
    return "959.00.125"

# ---------- TESTS ----------

def test_parse_price_runs():
    try:
        parse_price("1.234,56")
        parse_price(None)
    except Exception as e:
        pytest.fail(f"parse_price raised an exception: {e}")

@patch("core.main.handle_login")
def test_load_initial_cookies_runs(mock_login):
    mock_driver = MagicMock()
    mock_driver.get_cookies.return_value = [{"name": "session", "value": "xyz"}]
    mock_login.return_value = mock_driver

    try:
        load_initial_cookies()
    except Exception as e:
        pytest.fail(f"load_initial_cookies raised an exception: {e}")

def test_get_cookie_snapshot_runs(sample_cookies):
    with patch("core.main.cookies", sample_cookies):
        try:
            snapshot = get_cookie_snapshot()
            assert snapshot is not None
        except Exception as e:
            pytest.fail(f"get_cookie_snapshot raised an exception: {e}")

@patch("core.main.retrieve_product_data")
def test_does_product_exist_runs_and_returns_boolean(sample_product_code, sample_cookies):
    try:
        result = does_product_exist(sample_product_code, sample_cookies)
        assert isinstance(result, (bool, tuple))
        if isinstance(result, tuple):
            assert isinstance(result[0], bool)
    except Exception as e:
        pytest.fail(f"does_product_exist raised an exception: {e}")


    try:
        result = process_product(sample_product_code, sample_cookies)
        assert result is not None
    except Exception as e:
        pytest.fail(f"process_product raised an exception: {e}")
