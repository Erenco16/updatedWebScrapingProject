"""Tests for shared discovery/scraper URL routing and API-building logic."""
from spiders.hafele_parsing import (
    is_master_url,
    is_article_table_url,
    is_api_url,
    build_api_url,
    HAFELE_BASE,
    HAFELE_API_BASE,
)


class TestUrlClassification:
    """Test URL type detection."""

    def test_master_url_detection(self):
        url = (
            "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/"
            "tr_TR/-/TRY/ViewProduct-Start?SKU=P-02103503"
        )
        assert is_master_url(url) is True
        assert is_api_url(url) is False
        assert is_article_table_url(url) is False

    def test_api_url_detection(self):
        url = (
            "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/"
            "tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS"
            "?SKU=10670470&ProductQuantity=20000&SynchronizationAjaxToken=1"
        )
        assert is_api_url(url) is True
        assert is_master_url(url) is False
        assert is_article_table_url(url) is False

    def test_article_table_url_detection(self):
        url = (
            "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/"
            "tr_TR/-/TRY/ViewProduct-GetArticleTable?SKU=P-02103503"
        )
        assert is_article_table_url(url) is True
        assert is_master_url(url) is False
        assert is_api_url(url) is False

    def test_unrelated_url(self):
        url = "https://example.com/foo"
        assert is_master_url(url) is False
        assert is_api_url(url) is False
        assert is_article_table_url(url) is False


class TestApiUrlBuilding:
    """Test API URL construction from article number."""

    def test_build_api_url_with_article_number(self):
        article_no = "10670470"
        url = build_api_url(article_no)
        assert "SKU=10670470" in url
        assert "ProductQuantity=20000" in url
        assert "SynchronizationAjaxToken=1" in url
        assert url.startswith(HAFELE_API_BASE)
        assert HAFELE_API_BASE.startswith(HAFELE_BASE)
