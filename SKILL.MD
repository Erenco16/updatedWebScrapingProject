Here is the finalized, comprehensive `SKILL.md` file. It incorporates the specific HTML structures you provided for the accordion and product tiles, the requirement to migrate logic from your existing `scrape_all_products_main` branch, and the full architectural roadmap.

---

# SKILL: Scrapy-Redis Distributed Migration (Producer-Consumer + SQLite Persistence)

## Context & Architecture

We are migrating a legacy BeautifulSoup scraper (located in `scrape_all_products_main`) to a distributed Scrapy-Redis architecture. The goal is to maximize performance, ensure fault tolerance with SQLite, and automate reporting (Excel/Email).

### The Data Pipeline

1. **Producer (`read-product`):** Traverses the catalog, extracts SKUs, and pushes API requests to a **Redis** queue.
2. **Consumers (`process-products`):** A swarm of 10 nodes that pop URLs from Redis, fetch the API data, parse it using legacy BeautifulSoup logic, and **insert results into a central SQLite database**.
3. **Reporter (Post-Process):** A standalone Python script that reads from the SQLite database, generates an Excel file, and sends email notifications.

## Project Structure

```text
/hafele_project
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── /data            # Volume for persistent SQLite storage
├── /spiders
│   ├── hafele_harvester.py  # Producer
│   └── hafele_processor.py  # Consumer
├── /tests
│   └── test_redis_queue.py  # Integration tests for harvester
├── database.py      # SQLite connection and schema logic
└── reporter.py      # Logic for Excel generation & Emailing

```

## Step-by-Step Implementation Instructions

### Step 1: Migrate Logic from `scrape_all_products_main`

The LLM must explicitly pull the parsing logic from the `scrape_all_products_main` branch. This includes:

* The specific HTML element selection logic for product rows.
* The logic for handling the "seçiniz" or "Ögeyi Görüntüle" links.
* The legacy email formatting and Excel generation logic.

### Step 2: The Parsing Logic (Crucial HTML Context)

The spider **must** handle the following structures exactly as described:

#### 2A. The Accordion (No Pagination Here)

Capture links from the `panel-collapse` div.

* **Target:** `<a href="..." class="hflButtonSlim grey bottomLeft ot-button-35" ...>`
* **Action:** Extract the `href` from all accordion links, normalize to absolute URLs, and store for traversal.

#### 2B. The Product List & Pagination

On parametric search pages, extract product tiles **AND** handle pagination dynamically.

* **Product Target:** Extract the `data-value` attribute for the SKU on `<div data-value="58996941" class="row list-view article">`.
* **Pagination Target:** Look for the pagination wrapper `<div class="c-pagination__wrapper">`. Specifically, extract the `href` from the "Next" button: `<a class="c-pagination__btn c-pagination__btn-next ...">Devam</a>`.
* **Pagination Action:** If the "Next" (Devam) button exists, the spider must use `yield response.follow(next_page_url, callback=self.parse_product_list)` to continuously traverse all available pages.

#### 2C. API Target

Construct the final fetch URL for the Redis queue:
```
https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/ViewProduct-GetPriceAndAvailabilityInformationPDS?SKU={SKU}&ProductQuantity=20000&SynchronizationAjaxToken=1
```

### Step 3: Implementation Steps

1. **Orchestration (`docker-compose.yml`):** Define Redis, DB volume, Harvester, Processor (10 replicas), and Reporter services.
2. **Database (`database.py`):** Implement thread-safe `sqlite3` methods for `save_product(data)`.
3. **Producer (`hafele_harvester.py`):** Recursive crawler. It identifies all unique SKUs using the HTML classes above and yields the API URLs to the Redis queue.
4. **Consumer (`hafele_processor.py`):** Inherit from `RedisSpider`. It pops the API URL, performs the request, uses the **migrated BeautifulSoup logic** from `scrape_all_products_main`, and saves the result to SQLite.
5. **Reporter (`reporter.py`):** Queries SQLite, generates the Excel, and triggers the mailer logic from the original branch.

## Technical Settings (`settings.py`)

* **Redis:** `SCHEDULER`, `DUPEFILTER_CLASS`, and `SCHEDULER_PERSIST = True`.
* **Throughput:** `CONCURRENT_REQUESTS = 16`, `DOWNLOAD_DELAY = 1.0`.
* **Retry Logic:** `RETRY_TIMES = 5`, `RETRY_HTTP_CODES = [403, 429, 500, 502, 503, 504]`.

## Step 4: Integration Testing (`tests/test_redis_queue.py`)

Write a robust test suite using `pytest` and `redis-py` to validate that the Harvester and Pagination logic are working **before** spinning up the processing nodes.

### 4A. Test Requirements

* **Connection:** Connect to the local Redis instance defined in the environment variables (e.g., `redis://localhost:6379/0`).
* **Threshold Test:** Query the Scrapy-Redis queue key (typically `hafele:api_urls`).
* **Assertions:**
  * Assert that the queue is **NOT empty**.
  * Assert that the total count of items in the queue is **strictly greater than 1** (proving it successfully extracted multiple items and navigated pages).

### 4B. Root Cause Logging

Implement explicit failure messages. If the queue count is `0` or `1`, the test must fail and output a highly descriptive error indicating:

> *"Pagination or Extraction failed. The CSS selectors for the accordion, `data-value` attributes, or the `c-pagination__btn-next` button have likely changed."*

### 4C. Test Structure

```python
# tests/test_redis_queue.py
# - TestRedisQueue: Validates harvester output
#   - test_queue_not_empty
#   - test_queue_has_multiple_items  (proves pagination worked)
#   - test_queue_items_are_valid_urls
#   - test_harvester_status_is_done
#   - test_total_skus_match_queue_length
# - TestRedisConnection: Basic connectivity checks
#   - test_redis_ping
#   - test_redis_can_write_and_read
```

### 4D. Running the Tests

```bash
# Start Redis first
docker compose up redis -d

# Run the test suite
pytest tests/test_redis_queue.py -v

# If tests pass, start the full pipeline
docker compose up --build
```

## Output Requirements

1. Provide the complete code for all files.
2. Ensure the migration from `scrape_all_products_main` is seamless—the parsing functions should be identical to the legacy code.
3. Include thorough comments mapping the data flow (Harvester -> Redis -> Processor -> SQLite -> Reporter).
4. Ensure the SQLite connection logic includes a `timeout` parameter to handle simultaneous writes from the 10 consumer containers.

---

Before finishing up, confirm the changes via running docker compose up --build and if it can start up properly, if you cannot see at the end logs like stokta mevcut and some data being logged to the terminal then kill that process and then find out what was the cause of the failure and then fix it.