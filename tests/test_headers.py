"""Tests for HTTP headers constants."""
import pytest
from spiders.headers import (
    USER_AGENT,
    BROWSER_HEADERS,
    API_HEADERS,
    CHROME_ARGUMENTS,
    CHROME_EXPERIMENTAL_OPTIONS,
)


class TestHeadersConstants:
    """Verify headers match expected real-browser values."""

    def test_user_agent_is_linux_chrome(self):
        assert "Linux" in USER_AGENT
        assert "Chrome/143" in USER_AGENT
        assert "Mozilla/5.0" in USER_AGENT

    def test_browser_headers_has_required_keys(self):
        required = [
            "User-Agent", "Accept", "Accept-Language",
            "Sec-Ch-Ua", "Sec-Fetch-Dest", "Sec-Fetch-Mode",
            "Referer",
        ]
        for key in required:
            assert key in BROWSER_HEADERS, f"Missing header: {key}"

    def test_browser_headers_referer_is_hafele(self):
        assert "hafele.com.tr" in BROWSER_HEADERS["Referer"]

    def test_api_headers_includes_browser_headers(self):
        assert all(k in API_HEADERS for k in BROWSER_HEADERS)
        assert "X-Requested-With" in API_HEADERS

    def test_chrome_arguments_has_anti_detection(self):
        assert "--headless=new" in CHROME_ARGUMENTS
        assert "--disable-blink-features=AutomationControlled" in CHROME_ARGUMENTS
        assert "--no-sandbox" in CHROME_ARGUMENTS

    def test_chrome_experimental_options_excludes_automation(self):
        assert "enable-automation" in CHROME_EXPERIMENTAL_OPTIONS["excludeSwitches"]
