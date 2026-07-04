"""Tests for HafeleProcessor URL routing and API building logic."""
import pytest

from spiders.hafele_processor import (
    is_category_url,
    is_api_url,
    build_api_url,
    normalize_url,
    HAFELE_BASE,
    HAFELE_API_BASE,
)


class TestUrlClassification:
    """Test URL type detection."""

    def test_category_url_detection(self):
        url = "https://www.hafele.com.tr/tr/products/mobilya-kulplar-ve-kap-kollar-/10/"
        assert is_category_url(url) is True
        assert is_api_url(url) is False

    def test_api_url_detection(self):
        url = (
            "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/"
            "tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"
            "?SKU=10670470&ProductQuantity=20000&SynchronizationAjaxToken=1"
        )
        assert is_api_url(url) is True
        assert is_category_url(url) is False

    def test_non_category_url(self):
        assert is_category_url("https://example.com/foo") is False


class TestApiUrlBuilding:
    """Test API URL construction from article number."""

    def test_build_api_url_with_article_number(self):
        article_no = "10670470"
        url = build_api_url(article_no)
        assert "SKU=10670470" in url
        assert "ProductQuantity=20000" in url
        assert "SynchronizationAjaxToken=1" in url
        assert url.startswith(HAFELE_API_BASE)

    def test_normalize_url_absolute(self):
        href = "/tr/products/foo/"
        assert normalize_url(href) == f"{HAFELE_BASE}/tr/products/foo/"

    def test_normalize_url_with_fragment(self):
        href = "/tr/products/foo/#bar"
        assert "#" not in normalize_url(href)
