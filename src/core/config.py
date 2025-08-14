import os

# Multithreading and Rate Limiting Configuration

# Threading Configuration
# Tune MAX_WORKERS based on your infra; 4-8 is typical for I/O-bound scraping
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "5"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "25"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.5"))  # Base delay between requests in seconds
BATCH_DELAY = float(os.getenv("BATCH_DELAY", "1"))  # Delay between batches in seconds

# Cookie Management
COOKIE_REFRESH_INTERVAL = int(os.getenv("COOKIE_REFRESH_INTERVAL", "600"))  # seconds (10 minutes)
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", str(max(1, int(os.getenv("MAX_WORKERS", "5"))))))

# Rate Limiting
RATE_LIMIT_RETRY_DELAY = 30  # Wait time when rate limited (seconds)
MAX_RATE_LIMIT_RETRIES = 3  # Maximum retries for rate limited requests

# Request Configuration
REQUEST_TIMEOUT = 60  # Request timeout in seconds
MAX_RETRIES = 3  # Maximum retries for failed requests

# Progress Tracking
PROGRESS_UPDATE_INTERVAL = 10  # Update progress every N products

# Website Configuration
Hafele_BASE_URL = os.getenv("HAFELE_BASE_URL", "https://www.hafele.com.tr")
Hafele_LOGIN_URL = os.getenv("HAFELE_LOGIN_URL", "https://www.hafele.com.tr/tr")
Hafele_DOMAIN = os.getenv("HAFELE_DOMAIN", "hafele.com.tr")
Hafele_PRODUCT_API_PATH = os.getenv("HAFELE_PRODUCT_API_PATH", "/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS")
Hafele_SEARCH_API_PATH = os.getenv("HAFELE_SEARCH_API_PATH", "/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewParametricSearch-SimpleOfferSearch") 