import pytest
from unittest.mock import patch, MagicMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from core.main import refresh_cookies
import builtins

# Patch the open function globally
@pytest.fixture(autouse=True)
def patch_open():
    with patch.object(builtins, 'open', new_callable=MagicMock):
        yield

def test_refresh_cookies_success(monkeypatch):
    mock_driver = MagicMock()
    mock_driver.get_cookies.return_value = [{'name': 'sessionid', 'value': 'abc123'}]
    mock_driver.quit.return_value = None

    # Patch the real handle_login function from main.py
    monkeypatch.setattr("core.main.handle_login", lambda: mock_driver)
    monkeypatch.setattr("pickle.dump", lambda cookies, f: None)

    refresh_cookies()
    assert mock_driver.quit.called

def test_refresh_cookies_failure(monkeypatch):
    mock_driver = MagicMock()
    mock_driver.get_cookies.return_value = []  # Simulate no cookies
    mock_driver.quit.return_value = None

    monkeypatch.setattr("core.main.handle_login", lambda: mock_driver)
    monkeypatch.setattr("pickle.dump", lambda cookies, f: None)

    with pytest.raises(ValueError, match="No cookies retrieved!"):
        refresh_cookies()
    assert mock_driver.quit.called