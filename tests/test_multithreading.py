import pytest
from unittest.mock import patch, MagicMock
import time

# Import the multithreading components
from core.main import CookieManager, process_product_with_rate_limiting, create_error_result


class TestCookieManager:
    """Test the CookieManager class"""
    
    @patch('core.main.handle_login')
    def test_cookie_manager_initialization(self, mock_handle_login):
        """Test that CookieManager initializes correctly"""
        # Mock the login process
        mock_driver = MagicMock()
        mock_driver.get_cookies.return_value = [{"name": "test", "value": "test"}]
        mock_handle_login.return_value = mock_driver
        
        cookie_manager = CookieManager(max_sessions=2)
        
        assert len(cookie_manager.cookie_sessions) == 2
        assert cookie_manager.max_sessions == 2
        
        # Verify login was called for each session
        assert mock_handle_login.call_count == 2
    
    def test_get_available_session(self):
        """Test getting available sessions"""
        cookie_manager = CookieManager(max_sessions=2)
        
        # Mock sessions
        cookie_manager.cookie_sessions = [
            {'cookies': [{"name": "session1", "value": "test"}], 'last_used': 0, 'error_count': 0},
            {'cookies': [{"name": "session2", "value": "test"}], 'last_used': 100, 'error_count': 0}
        ]
        
        # Should return the least recently used session
        session = cookie_manager.get_available_session()
        assert session == [{"name": "session1", "value": "test"}]
    
    def test_mark_session_error(self):
        """Test marking sessions with errors"""
        cookie_manager = CookieManager(max_sessions=1)
        
        # Mock session
        test_cookies = [{"name": "test", "value": "test"}]
        cookie_manager.cookie_sessions = [
            {'cookies': test_cookies, 'last_used': 0, 'error_count': 0}
        ]
        
        # Mark error
        cookie_manager.mark_session_error(test_cookies)
        assert cookie_manager.cookie_sessions[0]['error_count'] == 1


class TestProductProcessing:
    """Test product processing functions"""
    
    def test_create_error_result(self):
        """Test creating standardized error results"""
        result = create_error_result("TEST123", "Test error")
        
        assert result["stock_code"] == "TEST123"
        assert result["stok_durumu"] == "HATA: Test error"
        assert result["kdv_haric_satis_fiyati"] is None
    
    @patch('core.main.retrieve_product_data')
    def test_process_product_success(self, mock_retrieve):
        """Test successful product processing"""
        # Mock successful response
        mock_retrieve.return_value = {
            "kdv_haric_tavsiye_edilen_perakende_fiyat": "100,00",
            "kdv_haric_net_fiyat": "80,00",
            "kdv_haric_satis_fiyati": "120,00",
            "stok_durumu": "stokta mevcut",
            "stock_amount": 50,
            "minimum_alis_fiyati": "10"
        }
        
        # Mock cookie manager
        cookie_manager = MagicMock()
        cookie_manager.get_available_session.return_value = [{"name": "test", "value": "test"}]
        
        result = process_product_with_rate_limiting("TEST123", cookie_manager)
        
        assert result["stock_code"] == "TEST123"
        assert result["stok_durumu"] == "stokta mevcut"
        assert result["stock_amount"] == 50
    
    @patch('core.main.retrieve_product_data')
    def test_process_product_rate_limit(self, mock_retrieve):
        """Test handling rate limiting"""
        # Mock rate limit response
        mock_retrieve.return_value = {
            "stok_durumu": "Rate limit exceeded"
        }
        
        cookie_manager = MagicMock()
        cookie_manager.get_available_session.return_value = [{"name": "test", "value": "test"}]
        
        result = process_product_with_rate_limiting("TEST123", cookie_manager)
        
        # Should return rate limit error
        assert result["stok_durumu"] == "Rate limit exceeded"
        cookie_manager.mark_session_error.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"]) 