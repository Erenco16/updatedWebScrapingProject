# Error Analysis — Häfele Web Scraper (2026-07-04 Run)

## Summary

| Metric | Value |
|--------|-------|
| Total Processors | 10 replicas |
| Processors that got a Selenium session (initial run) | 1 (processor-3) |
| Processors that got a Selenium session (after fix) | 5 (with 5 Chrome nodes) |
| Products scraped | **0** |
| Database rows at end | 5 (from previous run) |
| Run duration | ~10 minutes (600s timeout) |

**Root Cause: Cloudflare blocks headless Selenium entirely. Even with 5 nodes, all processors hit the "Just a moment..." challenge page and find 0 products.**

---

## 1. Selenium Grid Session Starvation

### Error Pattern
```
selenium.common.exceptions.SessionNotCreatedException: 
  Message: Could not start a new session. New session request timed out
```

### Affected Processors
- **processor-1** through **processor-10** (9 out of 10 failed)
- Only **processor-3** successfully created a session (`bff8ba815a6e12d3680a3e5cac69502f`)

### Root Cause
**10 processor replicas × 1 Chrome node slot = 9 timeout losers**

The `docker-compose.yml` deploys 10 processor replicas but only **1** Chrome node:

```yaml
  selenium-node-chrome:
    image: selenium/node-chrome:4.20.0-20240505
    # No deploy.replicas specified → defaults to 1
```

Selenium Grid 4.x queues session requests. When processor-3 grabbed the only slot at 15:58:17, all other 9 processors queued up and waited 5 minutes (default queue timeout) before getting `HTTP 500` + `SessionNotCreatedException`.

### Error Code Meaning
| Code | Meaning |
|------|---------|
| `SessionNotCreatedException` | Grid couldn't allocate a browser session |
| `HTTP 500` on `/session` | Hub's internal queue overflowed/timed out |
| `LocalNewSessionQueue.addToQueue` | Java-side queue handler rejected request |

### Fix
**Option A:** Scale Chrome nodes to match processor count:
```yaml
  selenium-node-chrome:
    deploy:
      replicas: 10
```

**Option B:** Reduce processors to 1-2 and run sequentially (slower but reliable).

**Option C:** Use a connection pool / retry with backoff instead of every processor grabbing a driver at startup.

---

## 2. Cloudflare Challenge Pages (Zero Products)

### Error Pattern
```
[Selenium] Page loaded: 27491 bytes, URL: https://www.hafele.com.tr/tr/products/...
📄 Page 1: Found 0 product rows
```

### Affected Processors
- **processor-3** (the only one that got a session)

### Root Cause
The ~27KB page responses are **Cloudflare "Just a moment..." challenge pages**, not real product listings. The anti-detection options in `middlewares.py` were insufficient:

```python
# These were NOT enough:
--disable-blink-features=AutomationControlled
excludeSwitches: ["enable-automation"]
```

Cloudflare detects:
1. **Headless Chrome** via `navigator.webdriver` and missing plugins
2. **Selenium Grid** via consistent window size, fast page loads, missing human-like delays
3. **Missing `cf_clearance` cookie** — required to bypass the challenge

### Error Code Meaning
| Code | Meaning |
|------|---------|
| `Found 0 product rows` | Page rendered but HTML had no `div.row.list-view.article` |
| `27491 bytes` | Challenge page size (~27KB is typical for Cloudflare interstitial) |
| `485248 bytes` | First category page might have been real HTML but still no products |

### Fix
1. **Add realistic delays** — `time.sleep(random.uniform(3, 8))` after page load
2. **Inject `cf_clearance` cookie** from a real browser session
3. **Use `undetected-chromedriver`** or **Puppeteer Stealth** instead of raw Selenium
4. **Try non-headless mode** with virtual display (`xvfb`) — harder to detect
5. **Rotate User-Agents** and add `Accept-Language` headers per request
6. **Check page title** — if it contains "moment", "cloudflare", "checking" → it's a challenge

---

## 3. Missing Cookies in Redis

### Error Pattern
```
⚠️ No cookies found in Redis
```

### Affected Processors
- **processor-2** (and likely others)

### Root Cause
The harvester saves cookies to `hafele:session:cookies`, but:
1. If harvester hasn't run yet, the key doesn't exist
2. If harvester was restarted, it might have cleared the key
3. Redis TTL might have expired the key

### Fix
- Ensure harvester runs **before** processors
- Add retry loop: wait up to 60s for cookies to appear
- Or have processors run without cookies (they'll get their own via Selenium)

---

## 4. Reporter Email Failures

### Error Pattern
```
❌ Failed to send Excel to e: {'e': (553, b'5.1.3 The recipient address <e> is not a valid...')}
```

### Root Cause
The `EMAIL_RECIPIENTS` env var is being parsed as individual characters:
```
EMAIL_RECIPIENTS=erenbasaran50@gmail.com
# Being split into: ['e', 'r', 'e', 'n', 'b', 'a', 's', ...]
```

### Fix
Check `.env` file format — likely missing quotes or using wrong delimiter.

---

## Action Plan

### Immediate (Fix Today)
1. ✅ **Write tests for all failures** (see `tests/test_docker_integration.py`)
2. ✅ **Document error codes** (this file)
3. 🔧 **Scale Chrome nodes to 5-10 replicas** in `docker-compose.yml`
4. 🔧 **Add Cloudflare bypass** — try `undetected-chromedriver` or non-headless
5. 🔧 **Fix email parsing** in reporter

### Short Term (This Week)
1. 🔧 **Add page-title detection** to identify challenge pages
2. 🔧 **Retry failed category URLs** with exponential backoff
3. 🔧 **Add proxy rotation** if IP gets blocked

### Long Term
1. 🔧 **Consider API-first approach** — reverse-engineer Häfele's internal API
2. 🔧 **Add monitoring dashboard** for Grid health, queue depth, success rate
