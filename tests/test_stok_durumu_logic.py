import pytest
from unittest.mock import patch

# Import functions from your actual modules (match Docker container structure)
from scraper.scraping_functions import (
    retrieve_product_data,
    extract_price_info,
    handle_singular_product,
    does_product_exist
)
from core.main import process_product

# Mock cookies for the test
mock_cookies = [{"name": "test", "value": "test"}]

@patch('core.main.cookies', mock_cookies)
@patch('core.main.retrieve_product_data')
def test_stok_durumu_valid(mock_retrieve):
    # Simulate retrieve_product_data returning a valid stok_durumu
    mock_retrieve.return_value = {
        'kdv_haric_tavsiye_edilen_perakende_fiyat': '139,13',
        'kdv_haric_net_fiyat': '115,94',
        'kdv_haric_satis_fiyati': '231,88',
        'stok_durumu': '5 ila 10 gün içinde',
        'stock_amount': 1366,
        'minimum_alis_fiyati': '24'
    }
    result = process_product('003.50.340')
    assert result['stok_durumu'] == '5 ila 10 gün içinde', f"Expected '5 ila 10 gün içinde', got {result['stok_durumu']}"

@patch('core.main.cookies', mock_cookies)
@patch('core.main.retrieve_product_data')
def test_stok_durumu_none(mock_retrieve):
    # Simulate retrieve_product_data returning None for stok_durumu
    mock_retrieve.return_value = {
        'kdv_haric_tavsiye_edilen_perakende_fiyat': '139,13',
        'kdv_haric_net_fiyat': '115,94',
        'kdv_haric_satis_fiyati': '231,88',
        'stok_durumu': None,
        'stock_amount': 1366,
        'minimum_alis_fiyati': '24'
    }
    result = process_product('003.50.340')
    assert result['stok_durumu'] == 'Stok verisi yok', f"Expected 'Stok verisi yok', got {result['stok_durumu']}"

@patch('core.main.cookies', mock_cookies)
@patch('core.main.retrieve_product_data')
def test_stok_durumu_empty_string(mock_retrieve):
    # Simulate retrieve_product_data returning empty string for stok_durumu
    mock_retrieve.return_value = {
        'kdv_haric_tavsiye_edilen_perakende_fiyat': '139,13',
        'kdv_haric_net_fiyat': '115,94',
        'kdv_haric_satis_fiyati': '231,88',
        'stok_durumu': '   ',
        'stock_amount': 1366,
        'minimum_alis_fiyati': '24'
    }
    result = process_product('003.50.340')
    assert result['stok_durumu'] == 'Stok verisi yok', f"Expected 'Stok verisi yok', got {result['stok_durumu']}" 