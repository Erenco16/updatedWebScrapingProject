# updatedSystemWebScrapingProject

I am building a web scraping projects for our supplier's updated system.

## Environment Variables

This project now supports configurable Hafele domain settings through environment variables. Create a `.env` file in the project root with the following variables:

### Required Variables
- `hafele_username`: Your Hafele account username
- `hafele_password`: Your Hafele account password
- `gmail_sender_email`: Gmail address for sending notifications
- `gmail_app_password`: Gmail app password for authentication

### Optional Variables (with defaults)
- `HAFELE_BASE_URL`: Base URL for Hafele website (default: https://www.hafele.com.tr)
- `HAFELE_DOMAIN`: Domain name for cookie management (default: hafele.com.tr)
- `HAFELE_PRODUCT_API_PATH`: API path for product data (default: /prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS)
- `HAFELE_SEARCH_API_PATH`: API path for product search (default: /prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewParametricSearch-SimpleOfferSearch)
- `GRID_URL`: Selenium Grid URL (default: http://selenium:4444/wd/hub)
- `USER_AGENT`: Browser user agent string

### Example .env file:
```
hafele_username=your_username
hafele_password=your_password
gmail_sender_email=your_email@gmail.com
gmail_app_password=your_app_password
HAFELE_BASE_URL=https://www.hafele.com.tr
HAFELE_DOMAIN=hafele.com.tr
```
