"""
monitoring/investigate_fallbacks.py

Deep root-cause for every reason the Dinler fallback fires in a given
run. Operates purely on data that's already on disk + does a *small*
sampled re-fetch against Hafele to capture raw bodies.

Steps:
1. Read data/dinler_fallback.log (JSONL) — every fallback this run
   emitted.
2. Group by (outcome, Dinler state, Dinler message) to see what
   categories exist.
3. Join against the products table so we know, for each fallback SKU,
   whether we ended up with price data (Hafele worked for prices but
   not stock) vs no price data (Hafele returned empty body).
4. For a bounded random sample (SAMPLE_PER_BUCKET per category),
   re-fetch Hafele's price/stock endpoint and classify the body:
     - empty            : 200 with 0 bytes
     - prices_no_stock  : non-zero, has class="price", no values-tr row
     - full             : non-zero, has both class="price" and values-tr
     - other            : status != 200 or body shape we didn't predict
5. Save raw bodies to monitoring/raw_hafele/<sku>.html so the next
   investigator can look at them without hitting Hafele again.
6. Print a summary table so the operator sees exactly WHY each
   fallback bucket happened, and crucially WHICH ones represented
   discontinued catalog entries vs genuine Hafele parse misses that
   we could fix in the parser.

Run with:  venv/bin/python monitoring/investigate_fallbacks.py
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapling.fetchers import Fetcher
import redis

from spiders.headers import API_HEADERS, IMPERSONATION_PROFILES

ROOT = Path(__file__).resolve().parent.parent
DINLER_LOG = ROOT / "data" / "dinler_fallback.log"
DB_PATH = ROOT / "data" / "products.db"
RAW_DIR = ROOT / "monitoring" / "raw_hafele"
RAW_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_PER_BUCKET = int(os.getenv("SAMPLE_PER_BUCKET", "6"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

API_URL_TMPL = (
    "https://www.hafele.com.tr/prod-live/web/WFS/Haefele-HTR-Site/tr_TR/-/TRY/"
    "ViewProduct-GetPriceAndAvailabilityInformationPDS"
    "?SKU={sku}&ProductQuantity=20000&SynchronizationAjaxToken=1"
)


def load_fallback_records() -> list[dict]:
    if not DINLER_LOG.exists():
        print(f"no fallback log at {DINLER_LOG}")
        return []
    out = []
    for raw in DINLER_LOG.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def db_lookup(skus: list[str]) -> dict[str, dict]:
    """Return {sku: {prices_present, stok_durumu, stock_amount}} for the
    DB rows corresponding to our fallback SKUs."""
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(skus))
    rows = conn.execute(
        f"""SELECT sku, kdv_haric_net_fiyat, kdv_haric_satis_fiyati,
                   kdv_haric_tavsiye_edilen_perakende_fiyat,
                   stok_durumu, stock_amount
            FROM products WHERE sku IN ({placeholders})""",
        skus,
    ).fetchall()
    conn.close()
    return {
        r["sku"]: {
            "any_price": any(r[c] for c in (
                "kdv_haric_net_fiyat",
                "kdv_haric_satis_fiyati",
                "kdv_haric_tavsiye_edilen_perakende_fiyat",
            )),
            "stok_durumu": r["stok_durumu"],
            "stock_amount": r["stock_amount"],
        }
        for r in rows
    }


def body_shape(body: bytes) -> str:
    if not body:
        return "empty"
    text = body.decode("utf-8", errors="replace")
    has_price = 'class="price"' in text or "<span class='price'>" in text
    has_values_tr = "values-tr" in text
    has_disc_marker = (
        "üretimden kaldır" in text.lower()
        or "satışa kapalı" in text.lower()
        or "discontinued" in text.lower()
    )
    if has_disc_marker:
        return "has_discontinued_marker"
    if has_values_tr and has_price:
        return "full"
    if has_price and not has_values_tr:
        return "prices_no_stock"
    return "other"


def fetch_raw(sku: str, cookies: dict) -> tuple[int, bytes]:
    url = API_URL_TMPL.format(sku=sku)
    try:
        resp = Fetcher.get(
            url, cookies=cookies, headers=API_HEADERS,
            impersonate=random.choice(IMPERSONATION_PROFILES),
            timeout=30,
        )
    except Exception as e:
        return 0, f"<fetch_error>{type(e).__name__}: {e}</fetch_error>".encode()
    for attr in ("body", "content"):
        v = getattr(resp, attr, None)
        if v:
            return (
                getattr(resp, "status_code", getattr(resp, "status", 0)),
                v if isinstance(v, (bytes, bytearray)) else str(v).encode("utf-8"),
            )
    t = getattr(resp, "text", "") or ""
    return (
        getattr(resp, "status_code", getattr(resp, "status", 0)),
        t.encode("utf-8"),
    )


def main() -> int:
    records = load_fallback_records()
    if not records:
        print("no Dinler fallback records to analyse")
        return 0

    print(f"loaded {len(records)} Dinler fallback records")
    unique_skus = {r["sku"] for r in records}
    print(f"unique SKUs: {len(unique_skus)}")

    # Bucket by (outcome, state, message_signature)
    buckets: dict[tuple, list[str]] = defaultdict(list)
    for r in records:
        state = r.get("state", "")
        msg_sig = (r.get("message") or r.get("error_signature") or "")[:120]
        buckets[(r["outcome"], state, msg_sig)].append(r["sku"])

    db_hits = db_lookup(sorted(unique_skus))
    with_price = sum(1 for sku in unique_skus if db_hits.get(sku, {}).get("any_price"))
    print(f"fallback-SKUs with Hafele price extracted: {with_price}/{len(unique_skus)}")
    print(f"  (price present + no stock_row = classic 'discontinued' pattern)")

    cookies = {}
    try:
        rc = redis.from_url(REDIS_URL, decode_responses=True)
        raw = rc.get("hafele:session:cookies")
        if raw:
            cookies = json.loads(raw)
            print(f"loaded {len(cookies)} session cookies from Redis")
    except Exception as e:
        print(f"could not read cookies from Redis ({e}); sampling without them")

    print()
    print(f"=== Fallback buckets (sampled, SAMPLE_PER_BUCKET={SAMPLE_PER_BUCKET}) ===")
    for (outcome, state, msg), skus in sorted(
        buckets.items(), key=lambda kv: -len(kv[1])
    ):
        print()
        print(f"[{len(skus):>4d}]  outcome={outcome}  state={state!r}")
        print(f"         msg={msg!r}")
        sample = random.sample(skus, min(SAMPLE_PER_BUCKET, len(skus)))
        shape_counts: Counter[str] = Counter()
        for sku in sample:
            status, body = fetch_raw(sku, cookies)
            shape = body_shape(body)
            shape_counts[shape] += 1
            out_file = RAW_DIR / f"{sku}.html"
            out_file.write_bytes(body or b"")
            print(f"    SKU={sku}  status={status}  len={len(body)}  shape={shape}  saved={out_file.name}")
        print(f"  shape totals (sample): {dict(shape_counts)}")

    print()
    print("saved sampled raw bodies to monitoring/raw_hafele/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
