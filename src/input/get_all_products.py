import imaplib
import email
from email.header import decode_header
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import zipfile
import pandas as pd
from pathlib import Path

# Load environment variables
load_dotenv()

EMAIL = os.getenv("gmail_sender_email")
PASSWORD = os.getenv("gmail_app_password")

IMAP_SERVER = "imap.gmail.com"
SAVE_DIR = "attachments"

os.makedirs(SAVE_DIR, exist_ok=True)


def decode_str(s):
    decoded, encoding = decode_header(s)[0]
    if isinstance(decoded, bytes):
        return decoded.decode(encoding or "utf-8", errors="replace")
    return decoded


# ---------- IMAP / Connection ----------

def connect_and_login():
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL, PASSWORD)
    return mail


def select_inbox(mail):
    mail.select("inbox")


# ---------- Search ----------

def build_search_criteria(sender, subject, since_dt_utc):
    since_date = since_dt_utc.strftime("%d-%b-%Y")
    return f'(SINCE "{since_date}" FROM "{sender}" SUBJECT "{subject}")'


def search_email_ids(mail, criteria):
    status, messages = mail.search(None, criteria)
    if status != "OK" or not messages or not messages[0]:
        return []
    return messages[0].split()


# ---------- Fetch / Time Filter ----------

def fetch_message(mail, msg_id):
    _, msg_data = mail.fetch(msg_id, "(RFC822)")
    return email.message_from_bytes(msg_data[0][1])


def fetch_message_headers(mail, msg_id):
    # Lightweight header-only fetch (faster than RFC822)
    _, msg_data = mail.fetch(msg_id, "(BODY.PEEK[HEADER])")
    return email.message_from_bytes(msg_data[0][1])


def get_message_datetime_utc(msg):
    date_hdr = msg.get("Date")
    if not date_hdr:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(date_hdr)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def is_within_window(msg_dt_utc, now_utc, hours):
    if msg_dt_utc is None:
        return False
    start = now_utc - timedelta(hours=hours)
    return start <= msg_dt_utc <= now_utc


def pick_latest_message_id(mail, msg_ids, now_utc, hours):
    """
    From msg_ids, pick the single latest message within the last `hours`.
    Returns None if none qualify.
    """
    best_id = None
    best_dt = None

    for msg_id in msg_ids:
        hdrs = fetch_message_headers(mail, msg_id)
        dt_utc = get_message_datetime_utc(hdrs)

        if not is_within_window(dt_utc, now_utc, hours):
            continue

        if best_dt is None or dt_utc > best_dt:
            best_dt = dt_utc
            best_id = msg_id

    return best_id


# ---------- Attachment Handling ----------

def iter_attachments(msg):
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get("Content-Disposition") is None:
            continue
        yield part


def get_zip_filename(part):
    filename = part.get_filename()
    if not filename:
        return None
    filename = decode_str(filename)
    if filename.lower().endswith(".zip"):
        return filename
    return None


def save_attachment(part, filename, save_dir=SAVE_DIR):
    filepath = os.path.join(save_dir, filename)
    with open(filepath, "wb") as f:
        f.write(part.get_payload(decode=True))
    return filepath


# ---------- ZIP -> Excel Extraction ----------

def is_excel_name(name: str) -> bool:
    n = name.lower()
    return n.endswith(".xlsx") or n.endswith(".xls") or n.endswith(".xlsm")


def safe_filename(name: str) -> str:
    return os.path.basename(name)


def extract_excel_from_zip(zip_path: str, out_dir: str = SAVE_DIR) -> str:
    excel_members = []

    with zipfile.ZipFile(zip_path, "r") as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            if is_excel_name(info.filename):
                excel_members.append(info)

        if len(excel_members) == 0:
            raise RuntimeError(f"No Excel file found inside zip: {zip_path}")

        if len(excel_members) > 1:
            names = [m.filename for m in excel_members]
            raise RuntimeError(f"Multiple Excel files found inside zip: {names}")

        member = excel_members[0]
        excel_name = safe_filename(member.filename)
        out_path = os.path.join(out_dir, excel_name)

        with z.open(member, "r") as src, open(out_path, "wb") as dst:
            dst.write(src.read())

    return out_path


def delete_file(path: str):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


# ---------- Orchestration ----------

def download_zip_attachment():
    now_utc = datetime.now(timezone.utc)

    mail = connect_and_login()
    try:
        select_inbox(mail)

        # ✅ last 60 hours requirement
        hours_window = 60

        criteria = build_search_criteria(
            sender=os.getenv("hafele_sender_email"),
            subject=os.getenv("hafele_username"),
            since_dt_utc=now_utc - timedelta(hours=hours_window),
        )

        msg_ids = search_email_ids(mail, criteria)
        if not msg_ids:
            print("❌ Email not found")
            return
        # Build list of candidate messages within the time window and sort newest->oldest
        candidates = []
        for msg_id in msg_ids:
            hdrs = fetch_message_headers(mail, msg_id)
            dt_utc = get_message_datetime_utc(hdrs)
            if is_within_window(dt_utc, now_utc, hours_window):
                candidates.append((msg_id, dt_utc))

        if not candidates:
            print(f"❌ No email found within the last {hours_window} hours")
            return

        candidates.sort(key=lambda x: x[1], reverse=True)

        found_excel = False
        # Iterate messages from newest to oldest until we find a ZIP that contains exactly one Excel
        for msg_id, msg_dt in candidates:
            try:
                msg = fetch_message(mail, msg_id)
            except Exception as e:
                print(f"⚠️ Failed to fetch message {msg_id}: {e}")
                continue

            print(f"Checking email id {msg_id} dated {msg_dt} for ZIP attachments...")
            found_zip_in_message = False

            for part in iter_attachments(msg):
                zip_filename = get_zip_filename(part)
                if not zip_filename:
                    continue

                found_zip_in_message = True
                zip_path = save_attachment(part, zip_filename)
                print(f"✅ ZIP downloaded: {zip_path} (from message {msg_id})")

                try:
                    excel_path = extract_excel_from_zip(zip_path, SAVE_DIR)
                    print(f"✅ Excel extracted: {excel_path}")

                    # Clean up ZIP and mark success
                    delete_file(zip_path)
                    found_excel = True
                    break
                except RuntimeError as e:
                    # Specific problem with this ZIP (no excel, or multiple excels) — try previous attachment/email
                    print(f"⚠️ Attachment {zip_path} invalid: {e} — trying previous email/attachment")
                    delete_file(zip_path)
                    continue
                except Exception as e:
                    print(f"⚠️ Unexpected error extracting {zip_path}: {e} — trying previous email/attachment")
                    delete_file(zip_path)
                    continue

            if found_excel:
                break

            if not found_zip_in_message:
                print(f"❌ No ZIP attachment found in email id {msg_id} — trying previous email")

        if not found_excel:
            print("❌ No valid ZIP with Excel found in recent emails")

    finally:
        mail.logout()


def get_latest_excel_in_attachments(save_dir: str = SAVE_DIR) -> str:
    """
    Returns the most recently modified Excel file path in attachments folder.
    Looks for .xlsx/.xls/.xlsm.
    """
    p = Path(save_dir)
    excel_files = []
    for ext in ("*.xlsx", "*.xls", "*.xlsm"):
        excel_files.extend(p.glob(ext))

    if not excel_files:
        raise FileNotFoundError(f"No Excel files found in '{save_dir}'")

    latest = max(excel_files, key=lambda f: f.stat().st_mtime)
    return str(latest)


def read_article_numbers_from_attachment_excel(excel_path: str) -> list:
    """
    Reads the attachment Excel and returns cleaned values from column 'Article no'.
    """
    df = pd.read_excel(excel_path, dtype=str)

    if "Article no" not in df.columns:
        raise KeyError(f"Column 'Article no' not found in attachment Excel. Found: {list(df.columns)}")

    codes = (
        df["Article no"]
        .astype(str)
        .str.strip()
        .replace({"": None, "nan": None, "None": None})
        .dropna()
        .tolist()
    )

    return codes


# ✅ UPDATED: delete previous rows, then write ONLY the new codes (no empty rows left)
def override_stockcode_in_product_codes(codes: list, target_excel_path: str = "product_codes.xlsx"):
    """
    Deletes previous rows and writes ONLY the new codes into product_codes.xlsx
    in column 'stockCode'. Ensures no trailing empty rows.
    """
    target_path = Path(target_excel_path)

    # Create a fresh DataFrame with exactly the new codes
    target_df = pd.DataFrame({"stockCode": pd.Series(codes, dtype="string")})

    # Overwrite the file completely
    target_df.to_excel(target_path, index=False)


def update_product_codes_from_latest_attachment():
    """
    Convenience method:
    - finds latest attachment Excel in attachments/
    - extracts 'Article no'
    - overwrites product_codes.xlsx so it contains ONLY the new stockCode rows
    """
    latest_excel = get_latest_excel_in_attachments(SAVE_DIR)
    codes = read_article_numbers_from_attachment_excel(latest_excel)

    # Optional: drop duplicates while preserving order (keeps file clean)
    seen = set()
    codes = [c for c in codes if not (c in seen or seen.add(c))]

    override_stockcode_in_product_codes(codes, "product_codes.xlsx")
    print(f"✅ Updated 'product_codes.xlsx' stockCode with {len(codes)} codes from: {latest_excel}")


if __name__ == "__main__":
    download_zip_attachment()
    update_product_codes_from_latest_attachment()