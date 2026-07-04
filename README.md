# Hafele Product Scraper

A distributed web scraping pipeline for extracting product price and stock data from [hafele.com.tr](https://www.hafele.com.tr). Built with **Scrapy-Redis**, **Selenium Grid**, and **SQLite**, orchestrated via **Docker Compose**.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Data Flow](#data-flow)
3. [Components](#components)
4. [Testing & Debugging](#testing--debugging)
5. [Queue Persistence](#queue-persistence)
6. [Setup & Run](#setup--run)
7. [Troubleshooting](#troubleshooting)

---

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌──────────────────┐
│  hafele.com.tr  │     │  Redis       │     │  SQLite DB       │
│  (source)       │────▶│  (queue)     │────▶│  (products.db)   │
└─────────────────┘     └──────────────┘     └──────────────────┘
         │                      │                      │
         ▼                      ▼                      ▼
  ┌────────────┐        ┌──────────────┐       ┌───────────────┐
  │ Harvester  │        │ 10× Processor│       │   Reporter    │
  │ (Producer) │        │  (Consumers) │       │ (Post-process)│
  └────────────┘        └──────────────┘       └───────────────┘
  Selenium Hub ─────▶ Chrome Node (browser automation)
```

| Service | Role | Type |
|---------|------|------|
| `hafele-harvester` | **Producer** — no login. Navigates `global_one_pim_catalog`, extracts category links from accordion panels, queues them in Redis | One-shot job |
| `processor` (×10) | **Consumer** — pops category URLs from Redis, extracts SKUs with pagination, fetches product API data, saves to SQLite | Long-running, parallel |
| `hafele-reporter` | **Post-processor** — generates Excel & sends email after completion | One-shot, depends on consumers |
| `hafele-redis` | **Message queue** — holds CATEGORY URLs between harvester and processors | Persistent volume |
| `selenium-hub` + `chrome` | **Browser automation** — used by harvester only | Shared infrastructure |

---

## Data Flow

1. **Harvester** — no login needed. Opens `hafele.com.tr/tr/products/ueruenler/global_one_pim_catalog/` → finds accordion panels → extracts sub-category links from `hflRange3 teaser` divs → pushes **category URLs** into Redis queue `hafele:api_urls`
2. **Processors** (10 parallel workers) pop **category URLs** from Redis → navigate to category page → extract SKUs with pagination ("Devam" button) → for each SKU, call the product API → parse HTML with BeautifulSoup → save structured data to SQLite
3. **Reporter** runs after all processors finish → queries SQLite → generates `.xlsx` report → emails it to configured recipients

---

## Components

### `spiders/hafele_harvester.py` — The Producer

**What it does (new flow — no login required):**
- Opens `hafele.com.tr/tr/products/ueruenler/global_one_pim_catalog/` via Selenium
- **No login** — directly scrapes the public catalog page
- Finds the `#accordion` container and all `panel-collapse` panels inside it
- Extracts sub-category links from `hflRange3 teaser modulTeaserAbout accordianModule` divs
- Queues **category URLs** (not API URLs) into Redis

**Target HTML structure:**
```html
<div id="accordion">
  <div class="panel-collapse collapse in" id="collapse347855">
    <div class="hflRange3 teaser modulTeaserAbout accordianModule">
      <a href="/tr/products/..." class="hflButtonSlim grey bottomLeft ot-button-35">
        Mobilya Kulpları
      </a>
    </div>
  </div>
</div>
```

**Key functions:**
- `extract_category_links(html)` — Parses accordion HTML, finds all sub-category `<a>` tags with `hflButtonSlim` class
- `push_category_link(redis_client, url)` — Queues raw category URLs into Redis

**⚠️ Important:** The harvester **always clears the old queue** (`redis_client.delete(REDIS_QUEUE_KEY)`) before running. See [Queue Persistence](#queue-persistence) for details.

---

### `spiders/hafele_processor.py` — The Consumer

**What it does:**
- Extends `scrapy_redis.spiders.RedisSpider` for distributed queue consumption
- Pops **category URLs** (not API URLs) from Redis queue `hafele:api_urls`
- For each category URL:
  - Navigates to the category page
  - Extracts SKUs from `data-value` attributes on product rows
  - Follows pagination via "Devam" (Next) button recursively
  - For each SKU found, calls the product API endpoint
- Parses product API HTML with BeautifulSoup:
  - Extracts 3 price fields (`kdv_haric_tavsiye_edilen_perakende_fiyat`, `kdv_haric_net_fiyat`, `kdv_haric_satis_fiyati`)
  - Extracts stock status and amount from table rows
  - Handles both single products and grouped products
- Saves results via `SQLitePipeline`

**Key functions:**
- `make_request_from_data(data)` — Pops category URL from Redis, creates Scrapy Request
- `parse_category(response)` — Parses category page: extracts SKUs + follows pagination
- `parse_product(response)` — Parses individual product API response
- `handle_singular_product(soup)` — Extracts price, stock, description for single products
- `handle_grouped_product(soup)` — Extracts data for grouped/multi-variant products

---

### `reporter.py` — Post-Processing

**What it does:**
- Reads all products from SQLite (`products.db`)
- Generates an Excel file: `YYYY_MM_DD_Hafele_Guncel_Stoklar.xlsx`
- Sends the Excel as email attachment to `gmail_receiver_email` and `gmail_receiver_email_2`
- Sends a plain-text completion summary to `informal_mail`

**Trigger:** Only runs after all 10 processors have exited (Docker Compose `depends_on: condition: service_completed_successfully`).

---

### `database.py` — SQLite Layer

Thread-safe SQLite persistence with:
- WAL mode (`PRAGMA journal_mode=WAL`) for concurrent writes from 10 processors
- Per-thread connection pooling
- `busy_timeout=30000` to prevent lock contention
- Schema: `products` table with SKU, stock_code, prices, stock status, amount, description, scraped_at

---

### `src/login.py` — Selenium Login

- Navigates hafele.com.tr
- Clicks through warning modal
- Enters username/password from `.env`
- Saves cookies to `src/cookies.pkl` and `src/session_info.json` for consumer reuse

---

### `src/selenium_client.py` — Grid Connection

- Creates `webdriver.Remote` connected to Selenium Grid
- Retries 10 times with 2s delay (handles Grid startup race conditions)
- Configures headless Chrome with custom User-Agent from `.env`

---

## Testing & Debugging

### Inspect the Redis Queue

```bash
# See how many items are in the queue
docker exec hafele-redis redis-cli LLEN hafele:api_urls

# View all URLs in the queue
docker exec hafele-redis redis-cli LRANGE hafele:api_urls 0 -1

# View first 5 URLs
docker exec hafele-redis redis-cli LRANGE hafele:api_urls 0 4
```

### Run Only the Harvester (URL Producer)

Start only Redis + Selenium, then run the harvester in isolation:

```bash
# 1. Start infrastructure
docker compose up -d redis selenium-hub chrome

# 2. Run only the harvester (--rm auto-deletes the container after exit)
docker compose run --rm harvester

# 3. Check what it queued
docker exec hafele-redis redis-cli LLEN hafele:api_urls
docker exec hafele-redis redis-cli LRANGE hafele:api_urls 0 -1
```

### Run the Test Suite

```bash
# 1. Ensure Redis is running locally (or via Docker)
docker compose up -d redis selenium-hub chrome

# 2. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Run tests (REDIS_URL must point to localhost outside Docker)
REDIS_URL=redis://localhost:6379 pytest tests/test_redis_queue.py -v
```

**Test coverage:**
- `test_redis_ping` — Redis connectivity
- `test_redis_can_write_and_read` — Basic read/write
- `test_queue_not_empty` — Harvester pushed items
- `test_queue_has_multiple_items` — Pagination worked (multiple SKUs)
- `test_queue_items_are_valid_urls` — URLs are well-formed Hafele API endpoints
- `test_harvester_status_is_done` — Harvester marked completion in Redis
- `test_total_skus_match_queue_length` — SKU count matches queue length

### Inspect SQLite Database

```bash
# Product count
sqlite3 data/products.db "SELECT COUNT(*) FROM products;"

# Recent products
sqlite3 data/products.db "SELECT sku, stock_code, stok_durumu, stock_amount FROM products ORDER BY scraped_at DESC LIMIT 10;"

# Full dump
sqlite3 data/products.db ".mode table" "SELECT * FROM products;"
```

### View Live Logs

```bash
# Harvester logs
docker logs -f hafele-harvester

# One processor
docker logs -f updatedwebscrapingproject-processor-1

# All processors
docker compose logs -f processor

# Reporter
docker logs -f hafele-reporter
```

---

## Queue Persistence

| Action | Queue Survives? | Why |
|--------|----------------|-----|
| `docker compose restart redis` | ✅ Yes | Named volume persists |
| `docker compose down` then `up -d redis` | ✅ Yes | Volume kept |
| `docker compose down -v` | ❌ No | `-v` destroys volumes |
| **Run `docker compose run --rm harvester`** | ❌ **No** | Harvester code explicitly clears old queue |
| Full `docker compose up` | ❌ **No** | Same — harvester runs first and wipes queue |

### Why the queue "disappears"

Line 378 in `spiders/hafele_harvester.py`:
```python
redis_client.delete(REDIS_QUEUE_KEY)  # Wipes old queue before each run
```

The harvester intentionally clears the queue to prevent stale URLs from being re-processed. If you want to **accumulate** queue data across runs, comment out this line.

### Redis data storage

Redis uses a Docker named volume `updatedwebscrapingproject_redis-data` with AOF persistence (`--appendonly yes`). This means data survives container restarts but is cleared by application logic (the harvester).

---

## Setup & Run

### Prerequisites

- Docker + Docker Compose
- `.env` file with credentials (see `.env.example`)

### Quick Start

```bash
# 1. Set credentials
cp .env.example .env
# Edit .env with your Hafele username/password, Gmail credentials, etc.

# 2. Start everything
docker compose up -d

# 3. Monitor
docker compose logs -f

# 4. When done, check output
ls data/*.xlsx
```

### Service Startup Order

Docker Compose enforces this via `depends_on` + `condition`:
1. `redis` starts (waits for `healthcheck: redis-cli ping`)
2. `selenium-hub` starts (waits for `/status` endpoint)
3. `chrome` starts (waits for hub to be healthy)
4. `harvester` runs (waits for redis + selenium to be ready)
5. `processor` ×10 starts (waits for harvester to finish)
6. `reporter` runs (waits for all processors to finish)

---

## Troubleshooting

### Queue is empty after harvester runs
- **Cause:** The Hafele website CSS selectors changed. Accordion links or product list pagination no longer match.
- **Fix:** Update selectors in `hafele_harvester.py` (look for `select("...")` calls). Check `extract_skus_from_page()` and `crawl_product_list_recursive()`.
- **Workaround:** The harvester already falls back to `data/product_codes.xlsx` mode.

### Processors run forever with 0 pages
- **Cause:** `scrapy-redis` spiders don't auto-close when the queue is empty. `SCHEDULER_IDLE_BEFORE_CLOSE` is unreliable.
- **Fix:** Already added `CLOSESPIDER_TIMEOUT: 600` (10 minute hard limit) in `hafele_processor.py`.
- **Manual fix:** `docker compose stop processor`

### Selenium Grid connection refused
- **Cause:** `GRID_URL` in `.env` points to `http://hafele-redis:4444` but you're running outside Docker.
- **Fix for local tests:** Set `GRID_URL=http://localhost:4444/wd/hub`
- **Fix for Docker:** Keep `GRID_URL=http://selenium-hub:4444/wd/hub`

### Redis hostname not found
- **Cause:** `REDIS_URL=redis://hafele-redis:6379` only resolves inside Docker Compose network.
- **Fix for local tests:** `REDIS_URL=redis://localhost:6379`
- **Fix for Docker:** Keep `REDIS_URL=redis://hafele-redis:6379`

---

## Project Structure

```
├── docker-compose.yml          # Full orchestration
├── docker-compose.yml          # Redis + Selenium infrastructure
├── Dockerfile.harvester          # Producer image
├── Dockerfile.processor          # Consumer image
├── Dockerfile.reporter           # Post-processor image
├── requirements.txt              # Python deps
├── .env                          # Secrets (gitignored)
│
├── spiders/
│   ├── hafele_harvester.py       # Producer: catalog crawl → Redis
│   ├── hafele_processor.py     # Consumer: Redis → SQLite
│   ├── pipelines.py              # SQLite persistence pipeline
│   └── settings.py               # Scrapy-Redis config
│
├── src/
│   ├── login.py                  # Selenium login flow
│   ├── selenium_client.py        # Grid connection with retries
│   └── send_mail.py              # Gmail email utilities
│
├── database.py                   # SQLite layer (thread-safe)
├── reporter.py                   # Excel generation + email
│
├── tests/
│   └── test_redis_queue.py       # Integration tests for harvester + Redis
│
└── data/
    ├── product_codes.xlsx        # Fallback stock codes (Excel)
    └── products.db               # SQLite output database
```
