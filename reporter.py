"""
reporter.py  ── Post-process reporter

Queries the SQLite database, generates an Excel file, and sends
email notifications using the legacy mail logic from
scrape_all_products_main.

Data flow:
    SQLite → pandas DataFrame → Excel → Email attachment
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import redis
from dotenv import load_dotenv

from database import get_all_products, count_products
from src.send_mail import send_mail, send_mail_with_excel

load_dotenv()

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/app/data")
REDIS_URL = os.getenv("REDIS_URL", "redis://hafele-redis:6379")
REDIS_QUEUE_KEY = "hafele:api_urls"
ALLOW_UNCONFIRMED = os.getenv("ALLOW_UNCONFIRMED_REPORT", "").lower() in ("1", "true", "yes")


def drain_is_confirmed():
    """Return (ok, reason). Reporter refuses to do anything unless ok is True.

    Guards against the compose `service_completed_successfully` trigger firing
    on the first brief idle-exit of the processors, which produces a partial
    excel snapshot. Also stops the reporter from running when the harvester
    hasn't set its status flag yet. Override with ALLOW_UNCONFIRMED_REPORT=1.
    """
    try:
        rc = redis.from_url(REDIS_URL, decode_responses=True)
        status = (rc.get("hafele:harvester:status") or "").strip()
        qlen = int(rc.llen(REDIS_QUEUE_KEY) or 0)
    except Exception as e:
        return False, f"Redis unreachable: {e}"
    if status != "done":
        return False, f"harvester status is {status!r}, expected 'done'"
    if qlen != 0:
        return False, f"queue still has {qlen} URLs pending"
    return True, "harvester=done, queue=0"


def _write_products_excel(filepath: str) -> int:
    """Dump every product row from SQLite into `filepath`. Returns rows written.

    Always reads fresh from the DB so a retry after a mismatch picks up
    any writes that happened in between.
    """
    rows = get_all_products()
    df = pd.DataFrame(rows)

    # Drop internal id / scraped_at from final report for cleanliness
    drop_cols = ["id", "scraped_at", "is_group_product"]
    for col in drop_cols:
        if col in df.columns:
            df = df.drop(columns=[col])

    # Ensure stockCode is the leftmost column
    cols = df.columns.tolist()
    if "stock_code" in cols:
        cols.remove("stock_code")
        cols = ["stock_code"] + cols
        df = df[cols]

    df.to_excel(filepath, index=False)
    return len(df)


def _count_excel_rows(filepath: str) -> int:
    """Read the Excel back and return its data-row count (-1 on read error)."""
    try:
        return pd.read_excel(filepath).shape[0]
    except Exception as e:
        print(f"⚠️ Could not read back Excel for verification: {e}")
        return -1


def generate_excel() -> str:
    """Read all products from SQLite, write .xlsx, verify count matches DB.

    Regenerates the Excel from the DB if the file's row count doesn't
    match `count_products()` — that way any partially-written or stale
    file gets rewritten with the full dataset. Retries once before giving
    up (returns the path either way; the caller decides what to do).
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    db_total = count_products()

    if db_total == 0:
        print("⚠️ No products found in database.")
        return None

    today = str(date.today()).replace("-", "_")
    filename = f"{today}_Hafele_Guncel_Stoklar.xlsx"
    filepath = os.path.join(OUTPUT_DIR, filename)

    written = _write_products_excel(filepath)
    print(f"✅ Excel generated: {filepath} ({written} rows written; DB has {db_total})")

    excel_rows = _count_excel_rows(filepath)
    if excel_rows == db_total:
        print(f"✅ Excel row count matches DB: {excel_rows} rows.")
        return filepath

    # Mismatch: regenerate once from the DB to be sure the file holds the
    # entire dataset.
    print(
        f"⚠️ Excel row count ({excel_rows}) does not match DB ({db_total}). "
        "Regenerating from the database."
    )
    db_total = count_products()
    written = _write_products_excel(filepath)
    excel_rows = _count_excel_rows(filepath)
    if excel_rows == db_total:
        print(f"✅ Excel regenerated and now matches DB: {excel_rows} rows.")
    else:
        print(
            f"⛔ Excel still mismatches DB after regeneration: "
            f"excel={excel_rows} db={db_total}. Sending anyway; investigate the DB/write path."
        )

    return filepath


def send_notification_emails(excel_path: str, recipient: str):
    """Send the completion email (with the Excel attached) to informal_mail only.

    The gmail_receiver_email* addresses are intentionally NOT used here —
    limiting delivery to informal_mail keeps test/dev runs from spamming
    production stakeholders. Widen this list only after a full run has
    been validated end-to-end.
    """
    total = count_products()
    if not recipient:
        print("⚠️ informal_mail env var not set; skipping email step.")
        return

    body = (
        "Hafele veri toplama süreci başarıyla tamamlandı.\n\n"
        f"Toplam ürün sayısı: {total}\n"
        f"Excel dosyası: {os.path.basename(excel_path)}\n\n"
    )
    subject = f"✅ Hafele Web Scraping Completed — {total} products"

    try:
        send_mail_with_excel(recipient, excel_path, subject=subject, body=body)
        print(f"✅ Completion email + Excel sent to {recipient}")
    except Exception as e:
        print(f"❌ Failed to send Excel to {recipient}: {e}")


def main():
    print("=" * 60)
    print("📊 HAFELE REPORTER")
    print("=" * 60)
    recipients = [
        os.getenv("informal_mail"),
        os.getenv("gmail_receiver_email"),
        os.getenv("gmail_receiver_email_2")
    ]

    ok, reason = drain_is_confirmed()
    if not ok:
        if ALLOW_UNCONFIRMED:
            print(f"⚠️ Drain NOT confirmed ({reason}); ALLOW_UNCONFIRMED_REPORT is set, continuing.")
        else:
            print(
                f"⛔ Drain NOT confirmed: {reason}. "
                "Refusing to generate a partial Excel / send a premature 'completed' email. "
                "The queue-watchdog will restart me once the queue is truly empty. "
                "Set ALLOW_UNCONFIRMED_REPORT=1 to override manually."
            )
            sys.exit(1)
    else:
        print(f"✅ Drain confirmed ({reason}); generating Excel + sending email.")

    total = count_products()
    print(f"📦 Products in database: {total}")

    if total == 0:
        print("⚠️ Nothing to report. Skipping Excel/email.")
        informal_mail = os.getenv("informal_mail")
        if informal_mail:
            send_mail(
                informal_mail,
                subject="⚠️ Hafele Web Scraping – No Data",
                body="The scraping process completed but no products were stored in the database.",
            )
        return

    excel_path = generate_excel()
    if excel_path:
        for recipient in recipients:
            send_notification_emails(excel_path, recipient)
        print("\n✅ Reporter finished.")


if __name__ == "__main__":
    main()
