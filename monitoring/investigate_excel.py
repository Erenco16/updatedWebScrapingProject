"""
monitoring/investigate_excel.py

Investigate the "empty stock at the top of the Excel" complaint.

The reporter writes ``get_all_products()`` which does
``SELECT * FROM products ORDER BY scraped_at DESC`` -- so "top of Excel"
means "most-recently-scraped rows".

We check:

1. How many rows have an empty stock_amount, and where they sit in the
   DESC-sorted ordering (first 50 rows vs rest)?
2. Which stok_durumu values dominate the empty-stock rows (eg. "Bu ürün
   Häfele tarafından üretimden kaldırılmıştır" -> Dinler says
   discontinued, so stock_amount legitimately nil).
3. Of the empty-stock rows, how many lack any price either (truly
   broken scrape) vs just lack stock_amount (expected for discontinued).
4. Cross-reference against the Dinler log so we can label each empty
   row as "Dinler-sourced discontinued", "Dinler-sourced unknown",
   "never fell back (Hafele happily gave us the row but no stock
   value)" etc.
5. Also opens the generated Excel (if present) and verifies the row
   order + stock column match the DB.

Run after the full pipeline + reporter has finished:
    venv/bin/python monitoring/investigate_excel.py
"""
from __future__ import annotations

import glob
import json
import sqlite3
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "products.db"
DINLER_LOG = ROOT / "data" / "dinler_fallback.log"


def load_dinler_sku_outcomes() -> dict[str, dict]:
    """Return {sku: {outcome, state, message}} for every fallback row."""
    out: dict[str, dict] = {}
    if not DINLER_LOG.exists():
        return out
    for raw in DINLER_LOG.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        out[str(rec.get("sku"))] = {
            "outcome": rec.get("outcome"),
            "state": rec.get("state"),
            "message": rec.get("message"),
        }
    return out


def main() -> int:
    if not DB.exists():
        print(f"no DB at {DB}")
        return 1
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT sku, stock_code, stok_durumu, stock_amount, "
        "kdv_haric_net_fiyat, kdv_haric_satis_fiyati, "
        "kdv_haric_tavsiye_edilen_perakende_fiyat, "
        "product_description, scraped_at "
        "FROM products ORDER BY scraped_at DESC"
    ).fetchall()
    conn.close()

    total = len(rows)
    if total == 0:
        print("DB has no products yet")
        return 0

    def _empty_stock(r):
        v = r["stock_amount"]
        return v is None or v == ""

    def _any_price(r):
        return any(r[c] for c in (
            "kdv_haric_net_fiyat",
            "kdv_haric_satis_fiyati",
            "kdv_haric_tavsiye_edilen_perakende_fiyat",
        ))

    empty = [r for r in rows if _empty_stock(r)]
    print(f"DB rows: {total}")
    print(f"rows with empty stock_amount: {len(empty)} ({100*len(empty)/total:.1f}%)")

    # Where do the empty-stock rows live in the sort order (top of Excel)?
    top50_empty = sum(1 for r in rows[:50] if _empty_stock(r))
    rest_empty = len(empty) - top50_empty
    print(f"  in top 50 of DESC-sorted output: {top50_empty}/50")
    print(f"  in remaining {total-50} rows: {rest_empty}/{total-50 if total > 50 else 0}")

    # Of the empty-stock rows, how many have price data?
    with_price = sum(1 for r in empty if _any_price(r))
    without = len(empty) - with_price
    print(f"empty-stock rows that at least have price: {with_price}/{len(empty)}")
    print(f"empty-stock rows that ALSO have no price (fully broken): {without}/{len(empty)}")

    # Dinler cross-reference
    dinler = load_dinler_sku_outcomes()
    print(f"\nDinler cross-reference ({len(dinler)} fallback skus known)")
    dinler_touched_empty = [r for r in empty if r["sku"] in dinler]
    print(f"  empty-stock rows that fell through to Dinler: {len(dinler_touched_empty)}")
    state_counts = Counter(dinler[r["sku"]].get("state") for r in dinler_touched_empty)
    print(f"  Dinler state distribution for those: {dict(state_counts)}")
    never_fallback = [r for r in empty if r["sku"] not in dinler]
    print(f"  empty-stock rows that NEVER fell through to Dinler: {len(never_fallback)}")
    if never_fallback:
        # These are the smoking gun: Hafele said something (we didn't
        # fall back) but we still ended up with empty stock. Show the
        # dominant stok_durumu values so we can see which parse path
        # dropped the stock number on the floor.
        print("  stok_durumu distribution (top 10):")
        for s, c in Counter(r["stok_durumu"] or "<NULL>" for r in never_fallback).most_common(10):
            print(f"    [{c:>4d}]  {s!r}")

    # Top of DESC ordering, show the first 10 rows explicitly so the
    # operator can see the exact pattern they complained about.
    print("\n=== first 10 rows (DESC scraped_at, == top of Excel) ===")
    for i, r in enumerate(rows[:10], 1):
        src = dinler.get(r["sku"], {})
        tag = f"dinler={src.get('state')}" if src else "no_dinler"
        print(f"  {i:>2d}. sku={r['sku']}  stock_amt={r['stock_amount']!r:<6s}  "
              f"stok_durumu={(r['stok_durumu'] or '')[:40]!r:<42s}  {tag}")

    # Cross-check the Excel file (if present)
    excels = sorted(glob.glob(str(ROOT / "data" / "*Hafele_Guncel_Stoklar.xlsx")))
    if excels:
        try:
            import pandas as pd
            path = excels[-1]
            df = pd.read_excel(path)
            print(f"\n=== excel cross-check ({path}) ===")
            print(f"excel rows: {len(df)}  cols: {list(df.columns)}")
            if "stock_amount" in df.columns:
                top50 = df.head(50)
                empty_top = (top50["stock_amount"].isna() | (top50["stock_amount"] == "")).sum()
                total_empty = (df["stock_amount"].isna() | (df["stock_amount"] == "")).sum()
                print(f"excel empty stock in top 50: {empty_top}/50")
                print(f"excel empty stock overall: {total_empty}/{len(df)}")
                # Does the top of the Excel actually align with top of DB?
                if "sku" in df.columns:
                    db_top_skus = [r["sku"] for r in rows[:10]]
                    # Excel's sku column is dot-formatted; strip the dots
                    # to compare against the DB's digits-only form.
                    excel_top_skus = [
                        str(s).replace(".", "") for s in df["sku"].head(10).tolist()
                    ]
                    print(f"DB top-10 skus    : {db_top_skus}")
                    print(f"excel top-10 skus : {excel_top_skus}")
                    print(f"order matches: {db_top_skus == excel_top_skus}")
        except Exception as e:
            print(f"excel inspect failed: {e}")
    else:
        print("\nno Excel generated yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
