"""
parsers.py
----------
Responsible for:
- Extracting price information from a BeautifulSoup page
- Extracting and formatting product description as responsive HTML

No Selenium or I/O here — pure BeautifulSoup parsing logic.
"""

from bs4 import BeautifulSoup

from src.util.logger_util import CustomLogger

log_manager = CustomLogger(__name__, log_file="parsers.log")
logger = log_manager.get_logger()

FETCH_FAILED = "FETCH_FAILED"


def extract_price_info(soup: BeautifulSoup) -> dict:
    """
    Extract the three price fields from a product page soup.

    Returns a dict with keys:
        - kdv_haric_tavsiye_edilen_perakende_fiyat
        - kdv_haric_net_fiyat
        - kdv_haric_satis_fiyati

    Values are set to FETCH_FAILED if fewer price elements than expected
    are found, which signals a partial page load to the caller.
    """
    prices = soup.select("span.price")

    result = {
        "kdv_haric_tavsiye_edilen_perakende_fiyat": prices[2].text.strip() if len(prices) > 2 else FETCH_FAILED,
        "kdv_haric_net_fiyat":                      prices[0].text.strip() if len(prices) > 0 else FETCH_FAILED,
        "kdv_haric_satis_fiyati":                   prices[1].text.strip() if len(prices) > 1 else FETCH_FAILED,
    }

    if any(v == FETCH_FAILED for v in result.values()):
        logger.info(f"  ⚠ Only {len(prices)} price element(s) found — page may have loaded partially")

    return result


def extract_product_description(soup: BeautifulSoup) -> str:
    """
    Extract product properties from the page and return them as
    a self-contained responsive HTML string.

    Returns "No description available" if the properties section
    cannot be found or is empty.
    """
    try:
        container = _find_properties_container(soup)
        if not container:
            logger.warning("⚠️ Could not find properties container")
            return "No description available"

        sections = container.find_all("div", class_="productPropertiesSection")
        if not sections:
            logger.warning("⚠️ Could not find product property sections")
            return "No description available"

        parsed = _parse_sections(sections)
        if not parsed:
            logger.warning("⚠️ No sections extracted")
            return "No description available"

        return _build_html(parsed)

    except Exception as e:
        logger.exception(f"Error extracting product description: {e}")
        import traceback
        traceback.print_exc()
        return "No description available"


# ── private helpers ───────────────────────────────────────────────────────────

def _find_properties_container(soup: BeautifulSoup):
    """Try multiple selectors to locate the properties container div."""
    container = soup.find("div", class_="hfl-product-properties-content")
    if container:
        return container

    label = soup.find(
        "div",
        class_="hfl-product-properties-label collapse__heading mobileNegativeMargin15"
    )
    if label:
        container = label.find_next("div", class_="hfl-product-properties-content")
        if container:
            return container

    collapse = soup.find("div", class_="collapse in")
    if collapse:
        container = collapse.find("div", class_="hfl-product-properties-content")
        if container:
            return container

    return None


def _parse_sections(sections) -> list:
    """Convert BeautifulSoup section elements into plain dicts."""
    result = []
    for section in sections:
        header = section.find("h3", class_="productPropertiesSectionHeader")
        body   = section.find("div", class_="productPropertiesSectionBody")
        if header and body:
            result.append({
                "header": header.get_text(strip=True),
                "body":   body.get_text(strip=True),
            })
        else:
            text = section.get_text(strip=True)
            if text:
                result.append({"header": None, "body": text})
    return result


def _build_html(sections: list) -> str:
    """Render parsed sections into a responsive HTML string."""
    html = '''<style>
    .product-description-container { max-width: 800px; margin: 0 auto; }
    @media (max-width: 768px) {
        .product-description-container { border-radius: 4px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
        .description-header { padding: 15px; }
        .description-content { padding: 15px; }
        .property-section { margin-bottom: 15px; padding-bottom: 15px; }
        .property-header { padding: 10px 12px; font-size: 14px; }
        .property-body { padding: 0 12px; font-size: 13px; }
        .intro-section { padding: 12px; margin-bottom: 15px; font-size: 13px; }
    }
    @media (max-width: 480px) {
        .description-header h1 { font-size: 18px; }
        .description-content { padding: 12px; }
        .property-section { margin-bottom: 12px; padding-bottom: 12px; }
        .property-header { padding: 8px 10px; font-size: 13px; border-left-width: 3px; }
        .property-body { padding: 0 10px; font-size: 12px; }
    }
</style>
<div class="product-description-container" style="background-color:#ffffff;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.1);overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,Cantarell,sans-serif;">
    <div class="description-header" style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;padding:20px;text-align:center;">
        <h1 style="font-size:clamp(20px,5vw,28px);font-weight:600;letter-spacing:0.5px;margin:0;">📋 Ürün Özellikleri</h1>
    </div>
    <div class="description-content" style="padding:20px;">
'''
    # Intro section (no header)
    if sections and sections[0]["header"] is None:
        html += (
            f'        <div class="intro-section" style="background-color:#f0f4ff;padding:15px;'
            f'border-radius:6px;margin-bottom:20px;border-left:4px solid #667eea;color:#333333;'
            f'line-height:1.6;font-size:clamp(13px,3.5vw,15px);">{sections[0]["body"]}</div>\n'
        )
        sections = sections[1:]

    for section in sections:
        html += (
            f'        <div class="property-section" style="margin-bottom:20px;padding-bottom:20px;border-bottom:1px solid #e0e0e0;">\n'
            f'            <div class="property-header" style="background-color:#f8f9fa;padding:12px 15px;'
            f'border-left:4px solid #667eea;border-radius:4px;margin-bottom:12px;font-weight:600;'
            f'color:#333333;font-size:clamp(14px,4vw,16px);">{section["header"]}</div>\n'
            f'            <div class="property-body" style="padding:0 15px;color:#555555;line-height:1.6;'
            f'font-size:clamp(13px,3.5vw,15px);word-break:break-word;">{section["body"]}</div>\n'
            f'        </div>\n'
        )

    html += '    </div>\n</div>'
    return html