# Hafele Product Scraper

Distributed pipeline for extracting price + stock data from [hafele.com.tr](https://www.hafele.com.tr). Built on **Scrapy-Redis** for distributed queueing, **Selenium Grid** for authenticated browser automation, and **SQLite** for persistence — all orchestrated by **Docker Compose**.

---

## Table of Contents

1. [Architecture — what runs where](#architecture--what-runs-where)
2. [How Cloudflare is defeated](#how-cloudflare-is-defeated)
3. [Data flow (end-to-end)](#data-flow-end-to-end)
4. [Components in detail](#components-in-detail)
5. [Docker image build, naming and replicas](#docker-image-build-naming-and-replicas)
6. [Testing individual components](#testing-individual-components)
7. [Inspecting the SQLite output](#inspecting-the-sqlite-output)
8. [Queue persistence & DB reset](#queue-persistence--db-reset)
9. [Setup & run](#setup--run)
10. [Troubleshooting](#troubleshooting)

---

## Architecture — what runs where

Running `docker compose up --build` starts **21 containers** in dependency order:

| # of containers | Service | Container name(s) | Purpose |
|---|---|---|---|
| 1 | `redis` | `hafele-redis` | Distributed queue + session-cookie store + harvester status flags. |
| 1 | `selenium-hub` | `selenium-hub` | Selenium Grid hub — routes browser sessions to worker nodes. |
| 5 | `chrome` (replicas) | `updatedwebscrapingproject-chrome-1..5` | Headless Chromium browser nodes registered with the hub. |
| 1 | `harvester` | `hafele-harvester` | One-shot **producer** — logs in, harvests the sitemap, seeds Redis. |
| 10 | `processor` (replicas) | `updatedwebscrapingproject-processor-1..10` | Parallel **consumers** — pop URLs, parse HTML, save to SQLite. |
| 1 | `reporter` | `hafele-reporter` | One-shot post-processor — generates Excel + sends email. |
| 1 | `log-collector` | `hafele-log-collector` | Sidecar that mounts docker.sock and tails every container above into a dedicated file under `./logs/`. |
| 1 | `queue-watchdog` | `hafele-queue-watchdog` | Sidecar that restarts exited processors while Redis still has work, and kicks the reporter after full drain. |

Compose enforces dependency order via `depends_on` + `condition`:

```
redis  ──►  selenium-hub  ──►  chrome ×5  ──►  harvester
                                                    │
                                       (harvester exits 0)
                                                    ▼
                                             processor ×10
                                                    │
                                    (all processors exit 0)
                                                    ▼
                                                reporter
```

---

## How Cloudflare is defeated

hafele.com.tr sits behind Cloudflare. Naive scraping hits either the "Just a moment…" JS challenge page or a 403. We work around it with three layers:

**1. Prefer paths that don't require JS challenge.**
The public **sitemap** (`/tr/sitemap.xml`) and the **app URLs** (`/prod-live/web/WFS/Haefele-HTR-Site/…/ViewProduct-Start?SKU=…`, `…/ViewProduct-GetPriceAndAvailabilityInformationPDS?SKU=…`) are Cloudflare-accepting when you send believable browser headers. The category *browse* pages (`/tr/products/…`) do trigger the JS challenge — the sitemap approach sidesteps that entirely.

**2. Send exactly what real Chrome 143 on Linux sends.**
`spiders/headers.py` defines the browser fingerprint used for every non-Selenium request. Every field matches a real request (User-Agent, `Sec-Ch-Ua*`, `Sec-Fetch-*`, `Accept-Encoding: gzip, deflate, br, zstd`, `Priority`, `Upgrade-Insecure-Requests`, TR-oriented `Referer`). Missing any of these = higher chance of a 403.

**3. Harvest a `cf_clearance` cookie via a real browser, and re-use it.**
Cloudflare accepts previously-solved challenges via the `cf_clearance` cookie. The harvester drives a real headless Chrome (via the Grid) through the login flow — Cloudflare stamps the browser with `cf_clearance` and Hafele stamps it with `sid` / `SessionInfoId` / `apiToken`. All those cookies are stored in Redis under `hafele:session:cookies`. Every processor loads them at spider startup and attaches them (as `cookies=…`) to every outgoing Scrapy `Request`. That's what lets bare-HTTP Scrapy requests carry both the Cloudflare-pass **and** the logged-in Hafele session.

---

## Data flow (end-to-end)

**Stage 0 — Harvester (once)**
1. Reset SQLite (`reset_database()` — drops + recreates `products`, `scrape_meta`).
2. Clear old Redis queue (`DEL hafele:api_urls`).
3. Log in through Selenium Grid: OneTrust cookie banner → country modal ("Stay Here", not "To the website of my country") → header login modal → submit → wait for session cookies.
4. Sanity-probe the API from inside the browser: if response length is ~7 KB and contains `values-tr`, we're logged in.
5. Dump every browser cookie into Redis as JSON: `SET hafele:session:cookies <json>`.
6. Fetch `/tr/sitemap.xml`, follow to the merged gzip sitemap, regex-extract every unique `P-XXXXXX` master ID (~4,781 as of writing).
7. `LPUSH` all master URLs into `hafele:api_urls`.
8. `SET hafele:harvester:status done`.

**Stage 1 — Processor: master URL → variants**
Each of the 10 processors runs `scrapy_redis.RedisSpider`, polling `hafele:api_urls` for URLs. Loads session cookies from Redis at `spider_opened`.

When it pops a **master URL** (`…/ViewProduct-Start?SKU=P-XXXXXX`):
- Fetches the HTML (with cookies).
- Extracts every `<div class="row list-view article" data-value="XXXXXXXX">` — the `data-value` is the numeric article number of a variant.
- Extracts the master's name, subline and meta-description, stores them in `hafele:master:meta` keyed by both the master SKU and each variant SKU.
- For each variant, builds the price API URL (`…/ViewProduct-GetPriceAndAvailabilityInformationPDS?SKU=…&ProductQuantity=20000&SynchronizationAjaxToken=1`) and `LPUSH`es it back into `hafele:api_urls`.
- If the master's HTML has no article rows inline, the processor falls back to the AJAX `ViewProduct-GetArticleTable` fragment referenced in the same page.

**Stage 2 — Processor: variant API → SQLite row**
When it pops a **price API URL**:
- Fetches the HTML (with cookies) — server responds with a small HTML fragment containing `<tr class="values-tr">` rows, `<span class="price">…</span>` blocks and JSON in `#ViewObjectJson`.
- **Stock status** is derived from the `values-tr` rows using the legacy priority: if any row's `<td.requestedPackageStatus .availability-flag>` text contains `stokta mevcut`, use that (with its `<td.qty-available>` as `stock_amount`). Otherwise use the first row that has both a qty and a flag. If no rows have flags at all, fall back to `#productAvailabilityInformation .availability-flag`. If even that's empty → `Stok bilgisi bulunamadi`.
- **Prices** come from the first three `span.price` elements: `[net, sales, suggested_retail]`.
- **Description** is the master's cached name + subline (both from `hafele:master:meta`).
- The item is yielded and picked up by `spiders.pipelines.SQLitePipeline`, which UPSERTs it into `products.db` keyed by `sku`.

**Stage 3 — Reporter**
- After all 10 processors exit 0, `hafele-reporter` starts.
- Reads every row of `products`, writes `data/YYYY_MM_DD_Hafele_Guncel_Stoklar.xlsx`.
- Sends the Excel to configured recipients (SMTP via Gmail app password).

**Watchdog — resume on premature exit**
Processors can exit before the queue drains (Scrapy's idle timer misfiring, `CLOSESPIDER_TIMEOUT` firing, transient network flap, etc.). The `queue-watchdog` sidecar polls Redis every 30 s once the harvester has finished:

- If **`LLEN hafele:api_urls > 0`** and **zero processors are running**, it runs `docker start` on every exited processor container. `SCHEDULER_PERSIST=True` means they pick up right where they left off. A 60 s cooldown prevents restart storms if the queue is genuinely stuck.
- If the **queue is empty** and **all processors are exited** and **the reporter is still in `Created`** state, it `docker start`s the reporter — this fixes the `docker compose up -d` quirk where the reporter never gets promoted from `Created` once the initial `up` command has returned.

The watchdog is a plain `docker:cli` container mounting `/var/run/docker.sock`. It has no dependency on the harvester or processors, so it's up from the very first second of the run and simply waits until `hafele:harvester:status == "done"` before acting.

---

## Components in detail

### `spiders/hafele_harvester.py` — Producer
- Selenium login through the Grid (see `login_and_save_cookies`).
- Sitemap-based SKU discovery (`extract_master_skus`).
- Persists cookies to Redis and calls `reset_database()` before starting.

### `spiders/hafele_processor.py` — Consumer
- Subclasses `scrapy_redis.spiders.RedisSpider`. `redis_key = "hafele:api_urls"`.
- `_load_cookies` (fires on `spider_opened`) pulls `hafele:session:cookies` and holds them on the spider.
- `make_request_from_data` classifies the popped URL (`is_master_url`, `is_article_table_url`, `is_api_url`) and routes it to the right callback, always with the session cookies attached.
- `parse_master` → variant discovery, `parse_article_table` → AJAX fallback, `parse_product_api` → the SQLite row.
- Concurrency is heavily throttled to survive Hafele's ~40 s/request authenticated backend: `CONCURRENT_REQUESTS=3`, `CONCURRENT_REQUESTS_PER_DOMAIN=3`, `DOWNLOAD_DELAY=1.0`, `DOWNLOAD_TIMEOUT=60`, and Cloudflare 5xx codes (`520–524`) added to retry list.

### `spiders/headers.py` — the Cloudflare-safe fingerprint
Two constants: `BROWSER_HEADERS` (for HTML fetches) and `API_HEADERS` (adds `X-Requested-With: XMLHttpRequest`). Both are Chrome 143 / Linux profile.

### `spiders/pipelines.py` — SQLite pipeline
Single-purpose: hands the item dict to `database.save_product()`.

### `database.py` — SQLite layer
- WAL mode (`PRAGMA journal_mode=WAL`) so 10 processors can UPSERT concurrently.
- Thread-local connections + module-level schema-init lock (idempotent + safe on cold start).
- `save_product` UPSERTs on `sku`.
- **`reset_database()`** drops both tables and recreates the schema — called by the harvester at the top of every run, so each `docker compose up` starts with an empty DB.
- Helpers: `get_all_products`, `count_products`, `get_scrape_meta`, `set_scrape_meta`.

### `reporter.py` — Excel + email
- Reads all rows, writes an .xlsx into `data/`, mails it out.

---

## Docker image build, naming and replicas

`docker compose up --build` walks every service in `docker-compose.yml`. For each one that has a `build:` block, it invokes `docker build` on the given context/Dockerfile and tags the result:

```
<compose-project-name>-<service-name>
```

The compose project name defaults to the parent directory name, lowercased with special chars stripped. This folder is `updatedWebScrapingProject`, so:

| Service (yml) | Dockerfile | Image tag |
|---|---|---|
| `harvester` | `Dockerfile.harvester` | `updatedwebscrapingproject-harvester` |
| `processor` | `Dockerfile.processor` | `updatedwebscrapingproject-processor` |
| `reporter` | `Dockerfile.reporter` | `updatedwebscrapingproject-reporter` |

Services without a `build:` block pull upstream images: `redis:7-alpine`, `seleniarm/hub:latest`, `seleniarm/node-chromium:latest`.

**Container names vs image names.** Where the yml has `container_name: X`, you get a container literally called `X` (e.g. `hafele-harvester`). Where the yml uses `deploy: replicas: N`, Compose auto-numbers containers `updatedwebscrapingproject-<service>-1 … -N` from the **single** image. That's how one `updatedwebscrapingproject-processor` image ends up running as 10 numbered containers.

**Cache behaviour.**
- Editing `spiders/*.py` invalidates only the last `COPY spiders/ /app/spiders/` layer → rebuild is ~1–3 s.
- Editing `requirements.txt` invalidates the pip layer + everything after → full rebuild.
- `docker compose build --no-cache` forces a complete rebuild.

**Replicas.**
- `chrome: deploy: replicas: 5` → 5 Chromium worker nodes register with the hub.
- `processor: deploy: replicas: 10` → 10 Scrapy consumers connect to Redis.

Each Chrome node advertises a single browser slot to the hub — so with 5 nodes you get 5 concurrent Selenium sessions. The harvester only needs 1 (login), so we're never near that ceiling.

---

## Testing individual components

### 1. Just the queue: start infra, don't run anything else

```bash
docker compose up -d redis selenium-hub chrome
docker exec hafele-redis redis-cli ping                    # expect PONG
docker exec hafele-redis redis-cli LLEN hafele:api_urls    # expect 0
```

### 2. Just the harvester (URL producer)

```bash
docker compose up -d redis selenium-hub chrome
docker compose run --rm harvester

# Verify
docker exec hafele-redis redis-cli GET hafele:harvester:status           # expect "done"
docker exec hafele-redis redis-cli GET hafele:harvester:total_masters    # expect ~4781
docker exec hafele-redis redis-cli LLEN hafele:api_urls                  # expect ~4781
docker exec hafele-redis redis-cli STRLEN hafele:session:cookies         # >2000 = cookies persisted
docker exec hafele-redis redis-cli LRANGE hafele:api_urls 0 4            # sample 5 URLs
```

### 3. Just one processor (isolate consumer behaviour)

Once the queue is seeded:

```bash
# Use --no-deps so we don't re-run the harvester (which would clear the queue!)
docker compose run --rm --no-deps processor \
  python -m scrapy crawl hafele_processor \
  -s REDIS_URL=redis://hafele-redis:6379 -s LOG_LEVEL=DEBUG
```

Send SIGINT (Ctrl+C) to graceful-shutdown.

### 4. Verify the Cloudflare bypass headers manually

```bash
# From your host, using the same header set as spiders/headers.py — should return HTTP 200:
curl -sI 'https://www.hafele.com.tr/tr/sitemap.xml' \
  -H 'User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36' \
  -H 'Accept-Language: en-GB,en;q=0.9' \
  -H 'Referer: https://www.hafele.com.tr/tr/'
```

### 5. Verify Selenium Grid has capacity

```bash
curl -s http://localhost:4444/status | jq '.value.ready, .value.nodes | length'
# → true
# → 5
```

### 6. Run the pytest integration tests

Tests spawn a fresh harvester subprocess and check the Redis state it produces.

```bash
docker compose up -d redis selenium-hub chrome
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
REDIS_URL=redis://localhost:6379 pytest tests/test_redis_queue.py -v
```

Coverage:
- `test_redis_ping`, `test_redis_can_write_and_read` — basic connectivity.
- `test_queue_not_empty`, `test_queue_has_multiple_items`, `test_queue_items_are_valid_urls` — the harvester actually produced something usable.
- `test_harvester_status_is_done` — the status flag was set.
- `test_total_skus_match_queue_length` — no leakage between `total_masters` counter and queue.

### 7. Watch logs

Two independent log sources, use whichever is easier for you.

**a. `docker logs` (live stream from the container):**

```bash
docker logs -f hafele-harvester
docker logs -f updatedwebscrapingproject-processor-1
docker compose logs -f processor                           # all 10 processors, interleaved
docker logs -f hafele-reporter
docker compose logs -f --tail=100 processor 2>&1 | grep "stokta mevcut"
```

Caveat: a container in `Created` state has no logs — its process was never launched. Check *why* it's stuck with `docker inspect <name> --format '{{json .State}}' | jq`.

**b. Per-container log files under `./logs/`:**

The `log-collector` sidecar mounts `/var/run/docker.sock` read-only, matches every container spawned by this project (regex `^hafele-|^updatedwebscrapingproject-|^selenium-hub$`), and runs `docker logs -f` on each, redirecting the output into its own file:

```
logs/
├── hafele-redis.log
├── selenium-hub.log
├── updatedwebscrapingproject-chrome-1.log  … -5.log
├── hafele-harvester.log
├── updatedwebscrapingproject-processor-1.log … -10.log
└── hafele-reporter.log
```

- Every `docker compose up --build` restarts the sidecar. Its first act is `rm -f /logs/*.log`, so **all files reset on each build**. Individual files also get truncated when a container is (re)tailed after a restart.
- The sidecar polls every 3 s for new containers, so late-starting services (reporter, replicas that come up in waves) still get their own log file.
- Because it uses `docker logs -f`, the files contain the exact same output as `docker logs <container>` — nothing is filtered.

Typical usage:

```bash
tail -f logs/hafele-harvester.log                                # live
grep -E "stokta mevcut|istek üzerine" logs/updatedwebscrapingproject-processor-*.log
wc -l logs/*.log                                                  # size overview
```

---

## Inspecting the SQLite output

`data/products.db` is a plain SQLite file. Open it with `sqlite3` or any SQLite GUI. Below are the queries I use to sanity-check a run.

### High-level: how much did we get?

```bash
sqlite3 data/products.db "SELECT COUNT(*) AS total_rows,
                                 COUNT(DISTINCT sku) AS distinct_skus
                          FROM products;"
```

### Coverage of price / description / stock fields

```bash
sqlite3 data/products.db "SELECT
  COUNT(*) AS total,
  SUM(CASE WHEN kdv_haric_net_fiyat IS NOT NULL AND kdv_haric_net_fiyat != '' THEN 1 ELSE 0 END) AS with_net_price,
  SUM(CASE WHEN kdv_haric_satis_fiyati IS NOT NULL AND kdv_haric_satis_fiyati != '' THEN 1 ELSE 0 END) AS with_sales_price,
  SUM(CASE WHEN product_description IS NOT NULL AND product_description != '' THEN 1 ELSE 0 END) AS with_description,
  SUM(CASE WHEN stock_amount IS NOT NULL THEN 1 ELSE 0 END) AS with_stock_amount
FROM products;"
```

### The stok_durumu breakdown (the real payoff of using login)

```bash
sqlite3 data/products.db "SELECT stok_durumu, COUNT(*) AS n
                          FROM products
                          GROUP BY stok_durumu
                          ORDER BY n DESC;"
```

Expected values (when logged in): `stokta mevcut`, `istek üzerine`, `1 ila 3 gün içinde`, `5 ila 10 gün içinde`, `10 ila 20 gün içinde`, `bir ay içinde`, `iki ay içinde`, `Stok bilgisi bulunamadi`.

### Was the run complete?

Compare DB rows against what the harvester queued and what's left in Redis:

```bash
# In the DB
sqlite3 data/products.db "SELECT COUNT(*) FROM products;"

# What the harvester queued
docker exec hafele-redis redis-cli GET hafele:harvester:total_masters

# What still needs processing
docker exec hafele-redis redis-cli LLEN hafele:api_urls
```

### Rate over the last N minutes

```bash
sqlite3 data/products.db "SELECT strftime('%H:%M', scraped_at) AS minute,
                                 COUNT(*)                     AS rows
                          FROM products
                          GROUP BY 1
                          ORDER BY minute DESC
                          LIMIT 15;"
```

### Sample rows

```bash
sqlite3 data/products.db "SELECT sku, stok_durumu, stock_amount,
                                 kdv_haric_net_fiyat,
                                 substr(product_description, 1, 60) AS description
                          FROM products
                          ORDER BY scraped_at DESC
                          LIMIT 20;"
```

### Rows with missing prices (deliverability check)

```bash
sqlite3 data/products.db "SELECT sku, stok_durumu, product_description
                          FROM products
                          WHERE kdv_haric_net_fiyat IS NULL
                             OR kdv_haric_net_fiyat = ''
                          LIMIT 20;"
```

### Full dump for one SKU

```bash
sqlite3 data/products.db ".mode line" "SELECT * FROM products WHERE sku = '82645712';"
```

---

## Queue persistence & DB reset

| Action | Redis queue | SQLite DB |
|---|---|---|
| `docker compose restart redis` | Survives | Untouched |
| `docker compose down` then `up -d redis` | Survives | Untouched |
| `docker compose down -v` | **Destroyed** (`-v` drops the named volume) | Untouched (host bind mount) |
| `docker compose up …` (harvester runs) | **Wiped** — harvester `DEL`s the key | **Wiped** — harvester calls `reset_database()` |
| Run only the processor with `--no-deps` | Survives | Untouched |

**Why every run starts clean.** The harvester's `main()` calls both `redis_client.delete("hafele:api_urls")` and `reset_database()` before it does anything else. This is intentional — resuming a partial run against a stale DB tends to double-count and produces confusing scrape stats. If you *do* want to resume without re-harvesting (queue has `SCHEDULER_PERSIST=True` so it survives), skip the harvester:

```bash
docker compose start processor          # picks up whatever's left in Redis
```

---

## Setup & run

**Prerequisites:** Docker + Docker Compose, plus a `.env` with:

```
hafele_username=...
hafele_password=...
gmail_sender_email=...
gmail_app_password=...
gmail_receiver_email=...
informal_mail=...
```

**Full run:**

```bash
docker compose up --build -d              # detached
docker compose logs -f harvester          # watch the login + sitemap seed
docker compose logs -f processor          # watch stock rows land
docker logs -f hafele-reporter            # after processors exit, watch the Excel emit
ls data/*.xlsx                            # the resulting report
```

Detached (`-d`) note: because the reporter depends on `service_completed_successfully`, and `up -d` returns as soon as the *first* set of containers is running, the reporter stays in `Created` state until the processors finish. Compose does **not** wake back up to start it. If your processors finished and the reporter is still `Created`, kick it manually:

```bash
docker compose up reporter                # foreground, streams logs
```

---

## Troubleshooting

### `logged_in_shape: False` in harvester logs
The Selenium login flow hit the country modal or OneTrust banner in the wrong order. Check `docker logs hafele-harvester` — you should see `cf_clearance` and `SecureSessionID` cookies logged. If you don't, the modal timing is off; add a `time.sleep(N)` before the login submit and rebuild.

### Massive `<524>` responses in processor logs
Hafele's authenticated backend can't keep up with the concurrency you're giving it — Cloudflare times out at 100 s and returns 524. The current settings (`CONCURRENT_REQUESTS_PER_DOMAIN=3`, `DOWNLOAD_DELAY=1.0`, 524 in retry list) are the point at which 524s stopped. If you re-tune upward, expect them back.

### Reporter in `Created` state after processors exit
The `queue-watchdog` sidecar promotes it automatically within its next poll (≤30 s). If it *stays* in `Created`, check `docker logs hafele-queue-watchdog` — the watchdog only promotes when the queue is `0` and every processor container is exited. If the queue still has work, the watchdog restarts processors instead of starting the reporter.

### `docker logs <container>` returns nothing
The container is in `Created` state — its process never ran. Use `docker inspect` to check dependency waits, not `docker logs`.

### Redis hostname unknown outside Docker
`REDIS_URL=redis://hafele-redis:6379` only resolves inside the Compose network. For local pytest set `REDIS_URL=redis://localhost:6379`.

---

## Project structure

```
├── docker-compose.yml         Full orchestration (7 service definitions, 19 containers)
├── Dockerfile.harvester       Producer image (adds chromium for local fallback)
├── Dockerfile.processor       Consumer image (slim Scrapy + BeautifulSoup)
├── Dockerfile.reporter        Post-processor image (pandas + openpyxl + smtplib)
├── requirements.txt
├── .env                       Secrets (gitignored)
│
├── spiders/
│   ├── hafele_harvester.py    Producer: login → sitemap → Redis
│   ├── hafele_processor.py    Consumer: Redis → SQLite (two-stage)
│   ├── headers.py             Cloudflare-safe header profile
│   ├── pipelines.py           SQLite persistence pipeline
│   └── settings.py            Scrapy-Redis config
│
├── src/
│   ├── login.py               Legacy Selenium login (reference)
│   ├── selenium_client.py     Grid connection helpers
│   └── send_mail.py           Gmail SMTP utilities
│
├── database.py                SQLite layer + reset_database()
├── reporter.py                Excel generation + email
│
├── tests/
│   └── test_redis_queue.py    pytest for harvester ↔ Redis
│
└── data/
    ├── product_codes.xlsx     Legacy fallback list
    └── products.db            SQLite output (regenerated on every run)
```
