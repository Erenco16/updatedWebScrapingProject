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


def extract_price_info(soup):
    prices = soup.select("span.price")
    units = soup.select("span.perUnit")
    return {
        "kdv_haric_tavsiye_edilen_perakende_fiyat": prices[2].text.strip() if len(prices) > 2 else None,
        "kdv_haric_net_fiyat": prices[0].text.strip() if len(prices) > 0 else None,
        "kdv_haric_satis_fiyati": prices[1].text.strip() if len(prices) > 1 else None,
    }


def extract_product_description(soup):
    """Extract product description from the product properties section and format as responsive HTML."""
    try:
        # Try multiple ways to find the properties container
        properties_container = soup.find("div", class_="hfl-product-properties-content")
        
        # If not found, try finding the label and getting the next sibling
        if not properties_container:
            label = soup.find("div", class_="hfl-product-properties-label collapse__heading mobileNegativeMargin15")
            if label:
                # The properties content should be a sibling or nearby
                properties_container = label.find_next("div", class_="hfl-product-properties-content")
        
        # Alternative: look for the collapse container
        if not properties_container:
            collapse_div = soup.find("div", class_="collapse in")
            if collapse_div:
                properties_container = collapse_div.find("div", class_="hfl-product-properties-content")
        
        if not properties_container:
            logger.warning("⚠️ Could not find properties container")
            return "No description available"
        
        sections = properties_container.find_all("div", class_="productPropertiesSection")
        if not sections:
            logger.warning("⚠️ Could not find product property sections")
            return "No description available"
        
        # Extract all product property sections
        html_sections = []
        for section in sections:
            header = section.find("h3", class_="productPropertiesSectionHeader")
            body = section.find("div", class_="productPropertiesSectionBody")
            
            if header and body:
                header_text = header.get_text(strip=True)
                body_text = body.get_text(strip=True)
                html_sections.append({
                    "header": header_text,
                    "body": body_text
                })
            else:
                # Handle sections without headers (like the first introductory section)
                body_text = section.get_text(strip=True)
                if body_text:
                    html_sections.append({
                        "header": None,
                        "body": body_text
                    })
        
        if not html_sections:
            logger.warning("⚠️ No html sections extracted")
            return "No description available"
        
        # Build responsive HTML with inline styles
        html_content = '''<style>
    .product-description-container {
        max-width: 800px;
        margin: 0 auto;
    }
    
    @media (max-width: 768px) {
        .product-description-container {
            border-radius: 4px;
            box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
        }
        
        .description-header {
            padding: 15px;
        }
        
        .description-content {
            padding: 15px;
        }
        
        .property-section {
            margin-bottom: 15px;
            padding-bottom: 15px;
        }
        
        .property-header {
            padding: 10px 12px;
            font-size: 14px;
        }
        
        .property-body {
            padding: 0 12px;
            font-size: 13px;
        }
        
        .intro-section {
            padding: 12px;
            margin-bottom: 15px;
            font-size: 13px;
        }
    }
    
    @media (max-width: 480px) {
        .description-header h1 {
            font-size: 18px;
        }
        
        .description-content {
            padding: 12px;
        }
        
        .property-section {
            margin-bottom: 12px;
            padding-bottom: 12px;
        }
        
        .property-header {
            padding: 8px 10px;
            font-size: 13px;
            border-left-width: 3px;
        }
        
        .property-body {
            padding: 0 10px;
            font-size: 12px;
        }
    }
</style>
<div class="product-description-container" style="background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1); overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;">
    <div class="description-header" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; text-align: center;">
        <h1 style="font-size: clamp(20px, 5vw, 28px); font-weight: 600; letter-spacing: 0.5px; margin: 0;">📋 Ürün Özellikleri</h1>
    </div>
    <div class="description-content" style="padding: 20px;">
'''
        
        # Add intro section if it exists (first section without header)
        if html_sections and html_sections[0]["header"] is None:
            html_content += f'        <div class="intro-section" style="background-color: #f0f4ff; padding: 15px; border-radius: 6px; margin-bottom: 20px; border-left: 4px solid #667eea; color: #333333; line-height: 1.6; font-size: clamp(13px, 3.5vw, 15px);">{html_sections[0]["body"]}</div>\n'
            html_sections = html_sections[1:]  # Remove from list
        
        # Add property sections
        for section in html_sections:
            html_content += f'''        <div class="property-section" style="margin-bottom: 20px; padding-bottom: 20px; border-bottom: 1px solid #e0e0e0;">
            <div class="property-header" style="background-color: #f8f9fa; padding: 12px 15px; border-left: 4px solid #667eea; border-radius: 4px; margin-bottom: 12px; font-weight: 600; color: #333333; font-size: clamp(14px, 4vw, 16px);">{section["header"]}</div>
            <div class="property-body" style="padding: 0 15px; color: #555555; line-height: 1.6; font-size: clamp(13px, 3.5vw, 15px); word-break: break-word;">{section["body"]}</div>
        </div>
'''
        
        html_content += '''    </div>
</div>'''
        
        return html_content
    except Exception as e:
        logger.exception(f"Error extracting product description: {e}")
        import traceback
        traceback.print_exc()
        return "No description available"
