"""Tests for Selenium middleware Cloudflare detection."""
import pytest
from spiders.middlewares import _is_challenge_page


class TestChallengeDetection:
    """Verify Cloudflare challenge page detection."""

    def test_detects_just_a_moment(self):
        html = "<title>Just a moment...</title><p>Checking your browser</p>"
        assert _is_challenge_page(html) is True

    def test_detects_cf_ray(self):
        html = '<html><script src="/cdn-cgi/challenge-platform/h/b/...">'
        assert _is_challenge_page(html) is True

    def test_normal_page_not_challenge(self):
        html = "<title>Häfele Mobilya Kulpları</title><div class='product-list'>"
        assert _is_challenge_page(html) is False

    def test_case_insensitive(self):
        html = "<title>JUST A MOMENT</title>"
        assert _is_challenge_page(html) is True
