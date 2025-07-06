# Multithreading and Rate Limiting Configuration

# Threading Configuration
MAX_WORKERS = 3  # Number of concurrent threads (conservative to avoid rate limiting)
BATCH_SIZE = 50  # Number of products to process in each batch
REQUEST_DELAY = 1.5  # Base delay between requests in seconds
BATCH_DELAY = 5  # Delay between batches in seconds

# Cookie Management
COOKIE_REFRESH_INTERVAL = 480  # Cookie refresh interval in seconds (8 minutes)
MAX_SESSIONS = 3  # Maximum number of cookie sessions to maintain

# Rate Limiting
RATE_LIMIT_RETRY_DELAY = 30  # Wait time when rate limited (seconds)
MAX_RATE_LIMIT_RETRIES = 3  # Maximum retries for rate limited requests

# Request Configuration
REQUEST_TIMEOUT = 60  # Request timeout in seconds
MAX_RETRIES = 3  # Maximum retries for failed requests

# Progress Tracking
PROGRESS_UPDATE_INTERVAL = 10  # Update progress every N products 