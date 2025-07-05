# Multithreading Implementation for Web Scraping

## Overview

This implementation adds multithreading capabilities to the web scraping system while respecting rate limits and Selenium login constraints. The solution uses multiple cookie sessions, batch processing, and intelligent rate limiting to maximize throughput without overwhelming the target server.

## Key Features

### 🔄 Cookie Pool Management
- **Multiple Sessions**: Maintains multiple cookie sessions (default: 3) to distribute load
- **Session Rotation**: Automatically rotates between sessions to balance usage
- **Error Recovery**: Automatically reinitializes sessions that encounter too many errors
- **Background Refresh**: Periodically refreshes cookies in the background

### ⚡ Rate Limiting Protection
- **Request Delays**: Configurable delays between requests (default: 1.5s + random jitter)
- **Batch Processing**: Processes products in configurable batches (default: 50 products)
- **Rate Limit Detection**: Detects 429, 403 status codes and rate limit messages in HTML
- **Automatic Retry**: Retries rate-limited requests with exponential backoff
- **Session Marking**: Marks problematic sessions for reinitialization

### 📊 Progress Tracking
- **Real-time Progress**: Shows completion percentage and processed count
- **Batch Progress**: Displays progress within each batch
- **Error Monitoring**: Tracks rate limit errors and other issues
- **Performance Metrics**: Reports total time and error counts

## Configuration

All multithreading parameters are configurable in `src/core/config.py`:

```python
# Threading Configuration
MAX_WORKERS = 3          # Number of concurrent threads
BATCH_SIZE = 50          # Products per batch
REQUEST_DELAY = 1.5      # Delay between requests (seconds)
BATCH_DELAY = 5          # Delay between batches (seconds)

# Cookie Management
COOKIE_REFRESH_INTERVAL = 480  # Cookie refresh interval (seconds)
MAX_SESSIONS = 3               # Maximum cookie sessions

# Rate Limiting
RATE_LIMIT_RETRY_DELAY = 30    # Wait time when rate limited
MAX_RATE_LIMIT_RETRIES = 3     # Maximum retries for rate limited requests
```

## Architecture

### CookieManager Class
- Manages multiple cookie sessions
- Handles session rotation and error tracking
- Automatically reinitializes problematic sessions

### Batch Processing
- Processes products in configurable batches
- Uses ThreadPoolExecutor for concurrent processing
- Maintains controlled concurrency to avoid rate limiting

### Rate Limit Handling
- Detects rate limiting through HTTP status codes and HTML content
- Implements exponential backoff for retries
- Marks problematic sessions for reinitialization

## Usage

The multithreading is automatically enabled when running `main.py`. The system will:

1. Initialize multiple cookie sessions
2. Process products in batches with controlled concurrency
3. Monitor for rate limiting and handle errors gracefully
4. Display real-time progress updates
5. Send completion notifications via email

## Performance Benefits

- **3x Faster**: With 3 workers, processing is approximately 3x faster than single-threaded
- **Resilient**: Handles rate limiting and errors without stopping
- **Scalable**: Easy to adjust worker count and batch sizes
- **Monitorable**: Real-time progress tracking and error reporting

## Safety Features

- **Conservative Defaults**: Default settings are conservative to avoid rate limiting
- **Error Recovery**: Automatic recovery from session errors
- **Graceful Degradation**: Continues processing even if some sessions fail
- **Resource Management**: Proper cleanup of threads and sessions

## Testing

Run the multithreading tests:

```bash
python -m pytest tests/test_multithreading.py -v
```

## Docker Compatibility

The implementation is fully compatible with Docker containers:
- Uses relative paths that work in containerized environments
- Maintains the same import structure as the original code
- No changes to Docker configuration required

## Monitoring

The system provides comprehensive monitoring:
- Progress percentage and counts
- Rate limit error tracking
- Session health monitoring
- Performance metrics

## Troubleshooting

### High Rate Limit Errors
- Reduce `MAX_WORKERS` in config
- Increase `REQUEST_DELAY`
- Increase `BATCH_DELAY`

### Session Errors
- Check login credentials
- Verify network connectivity
- Monitor session initialization logs

### Performance Issues
- Increase `MAX_WORKERS` (cautiously)
- Reduce `BATCH_SIZE`
- Adjust delays based on server response 