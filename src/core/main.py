import os
import sys
import pickle
import pandas as pd
from dotenv import load_dotenv
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
import base64
import json
import re
from urllib.parse import unquote

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

# Load env
load_dotenv()

# Import project functions
from scraper.scraping_functions import retrieve_product_data
from scraper.send_mail import send_mail_without_excel, send_mail_with_excel
from hafele_login import handle_login as hafele_login
from core.config import *

# Constants
BASE_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
INPUT_FILE = os.path.join(ROOT_DIR, "input", "product_codes.xlsx")
OUTPUT_FILE = os.path.join(ROOT_DIR, "output", "product_data_results.xlsx")
COOKIE_FILE = os.path.join(ROOT_DIR, "shared", "cookies.pkl")
BASE_PRODUCT_URL = f"{Hafele_BASE_URL}{Hafele_PRODUCT_API_PATH}"

# Global state
progress_lock = threading.Lock()
refresh_lock = threading.Lock()
processed_count = 0
total_count = 0
rate_limit_errors = 0


# -------------------- Cookie Manager --------------------

class CookieManager:
    """
    Log in ONCE (single driver), open N tabs (per requirement), capture cookies,
    quit driver, then reuse cookies with requests across threads.
    Refresh only when clearly unauthorized or token likely expired.
    """
    def __init__(self, max_sessions=MAX_WORKERS):
        self.max_sessions = max_sessions
        self.cookie_sessions = []  # list of dicts: {'cookies': [...], 'last_used': ts, 'expires_at': ts}
        self.session_lock = threading.Lock()

        # small safety margin; but we avoid hard failing if missing expiries
        self.clock_skew_secs = 30
        # very light validation cadence
        self.min_validation_gap_secs = 60

        self.initialize_sessions()

    # -------- helpers to parse/compute expiry (safe & conservative) --------
    def _get_cookie(self, cookies, name):
        if not cookies:
            return None
        for c in cookies:
            if c.get("name") == name:
                return c
        return None

    def _safe_cookie_expiry_secs(self, cookie_dict):
        """Return expiry (UTC seconds) if meaningful; treat 0 as 'session cookie' => None."""
        if not cookie_dict:
            return None
        exp = cookie_dict.get("expiry") or cookie_dict.get("expires")
        try:
            if exp is None:
                return None
            exp = float(exp)
            if exp == 0:
                return None
            return exp
        except Exception:
            return None

    def _parse_api_token_internal_expiry_secs(self, cookies):
        """
        apiToken value is URL-encoded JSON with key 'apiToken'.
        The middle Base64 token often contains a 13-digit ms epoch. Use the max 13-digit match.
        """
        try:
            api_cookie = self._get_cookie(cookies, "apiToken")
            if not api_cookie:
                return None

            raw_val = api_cookie.get("value", "")
            if not raw_val:
                return None

            decoded = unquote(raw_val)
            obj = json.loads(decoded) if decoded.startswith("{") else None
            if not obj or "apiToken" not in obj:
                return None

            token_str = obj["apiToken"]
            parts = token_str.split("|")
            if len(parts) < 2:
                return None

            middle_b64 = parts[1]
            pad = "=" * (-len(middle_b64) % 4)
            decoded_bytes = base64.b64decode(middle_b64 + pad)
            decoded_txt = decoded_bytes.decode("utf-8", errors="ignore")

            ms_candidates = re.findall(r"\b1\d{12}\b", decoded_txt)
            if not ms_candidates:
                return None

            ms_epoch = max(int(x) for x in ms_candidates)
            return ms_epoch / 1000.0
        except Exception:
            return None

    def _recompute_session_expiry(self, session_dict):
        """
        Compute a single 'expires_at' using apiToken's browser expiry and payload expiry.
        Fallback to created_at + COOKIE_REFRESH_INTERVAL if unavailable.
        """
        cookies = session_dict.get("cookies", [])
        now_ts = time.time()
        candidates = []

        api_cookie = self._get_cookie(cookies, "apiToken")
        api_cookie_exp = self._safe_cookie_expiry_secs(api_cookie)
        if api_cookie_exp:
            candidates.append(api_cookie_exp)

        api_internal_exp = self._parse_api_token_internal_expiry_secs(cookies)
        if api_internal_exp:
            candidates.append(api_internal_exp)

        if candidates:
            session_dict["expires_at"] = min(candidates)
        else:
            # be permissive — if we can't parse, just set a refresh horizon window
            created_at = session_dict.get("created_at") or now_ts
            session_dict["expires_at"] = created_at + float(COOKIE_REFRESH_INTERVAL)

        session_dict["last_validated_at"] = now_ts

    # -------- lifecycle --------
    def initialize_sessions(self):
        """Login once, open N tabs (as required), capture cookies, quit driver, replicate to N sessions."""
        print(f"🔄 Initializing {self.max_sessions} cookie sessions from a single login...")

        try:
            driver = hafele_login.handle_login()  # returns logged-in driver (tab 1)
            # Open additional tabs to satisfy the requirement (cookies are shared anyway)
            for i in range(1, self.max_sessions):
                driver.execute_script("window.open('https://www.hafele.com.tr/tr/', '_blank');")
                # Switch to the new tab to ensure session is established server-side
                driver.switch_to.window(driver.window_handles[i])
                time.sleep(0.5)

            # Return to first tab (optional)
            driver.switch_to.window(driver.window_handles[0])
            time.sleep(0.5)

            # Grab cookies once (they are shared across tabs)
            base_cookies = driver.get_cookies()

            # Quit immediately — we only need cookies
            try:
                driver.quit()
            except Exception:
                pass

            # Create N logical sessions using the same cookie jar
            for i in range(self.max_sessions):
                sess = {
                    'cookies': [dict(c) for c in base_cookies],  # shallow copy list of dicts
                    'last_used': time.time(),
                    'created_at': time.time(),
                    'error_count': 0,
                    'source': f'login_copy_{i+1}'
                }
                self._recompute_session_expiry(sess)
                self.cookie_sessions.append(sess)

            # Persist for external tools if needed
            try:
                os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)
                with open(COOKIE_FILE, "wb") as f:
                    pickle.dump(base_cookies, f)
                print("💾 Base cookies saved to file")
            except Exception as e:
                print(f"⚠️ Failed to save cookies: {e}")

            print(f"✅ Cookie manager initialized with {len(self.cookie_sessions)} sessions")

        except Exception as e:
            print(f"❌ Failed to initialize sessions: {e}")

    def _light_validate(self, session_dict):
        """
        Lightweight check: require apiToken present; consider expiry only if known and clearly past.
        Do NOT aggressively invalidate — rely on on-demand refresh when a request fails.
        """
        cookies = session_dict.get('cookies') or []
        if not self._get_cookie(cookies, "apiToken"):
            return False

        now_ts = time.time()
        expires_at = session_dict.get("expires_at")
        last_val = session_dict.get("last_validated_at")

        # Use cached decision if we validated very recently
        if last_val and expires_at and (now_ts - float(last_val) < self.min_validation_gap_secs):
            return (not expires_at) or ((now_ts + self.clock_skew_secs) < float(expires_at))

        # Recompute once in a while
        self._recompute_session_expiry(session_dict)
        expires_at = session_dict.get("expires_at")
        return (not expires_at) or ((now_ts + self.clock_skew_secs) < float(expires_at))

    def get_available_session(self):
        """Pick the LRU session that passes the light check, else return the LRU anyway (we'll refresh on demand)."""
        with self.session_lock:
            if not self.cookie_sessions:
                print("❌ No cookie sessions available")
                return None

            # Prefer one that passes light check
            for session in sorted(self.cookie_sessions, key=lambda x: x['last_used']):
                if self._light_validate(session):
                    session['last_used'] = time.time()
                    return session['cookies']

            # If none pass light check, return LRU; the caller will trigger refresh if needed
            session = min(self.cookie_sessions, key=lambda x: x['last_used'])
            session['last_used'] = time.time()
            return session['cookies']

    def refresh_all_sessions(self):
        """
        Single new login; replace cookies in all sessions; recompute expiries.
        Use a process-wide lock to avoid dogpiling.
        """
        with refresh_lock:
            try:
                print("🔄 Performing global cookie refresh (single login)...")
                driver = hafele_login.handle_login()
                new_cookies = driver.get_cookies()
                try:
                    driver.quit()
                except Exception:
                    pass

                with self.session_lock:
                    for sess in self.cookie_sessions:
                        sess['cookies'] = [dict(c) for c in new_cookies]
                        sess['created_at'] = time.time()
                        sess['last_used'] = time.time()
                        sess['error_count'] = 0
                        self._recompute_session_expiry(sess)

                try:
                    with open(COOKIE_FILE, "wb") as f:
                        pickle.dump(new_cookies, f)
                    print("💾 Refreshed cookies saved to file")
                except Exception as e:
                    print(f"⚠️ Failed to save refreshed cookies: {e}")

                print("✅ Global cookie refresh complete")
                return True

            except Exception as e:
                print(f"❌ Global cookie refresh failed: {e}")
                return False


# -------------------- Scraping helpers --------------------

def parse_price(price_str):
    if price_str is None:
        return None
    cleaned = price_str.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def looks_unauthorized(data_obj):
    """
    Heuristics to detect expired/invalid cookies:
    - explicit redirect/login markers,
    - empty critical fields,
    - status-like fields.
    """
    if not isinstance(data_obj, dict):
        return False
    text_blob = json.dumps(data_obj).lower()
    if "unauthorized" in text_blob or "yetkisiz" in text_blob:
        return True
    if "login" in text_blob or "giriş" in text_blob:
        return True
    # If site-specific marker exists (e.g., {"stok_durumu":"Unauthorized"}), catch it:
    if data_obj.get("stok_durumu") in ("Unauthorized", "Forbidden", "Not logged in"):
        return True
    return False


def hit_rate_limited(data_obj):
    if not isinstance(data_obj, dict):
        return False
    sd = str(data_obj.get("stok_durumu", "")).lower()
    return "rate limit" in sd or sd == "rate limit exceeded"


def create_error_result(code, error_msg):
    return {
        "stock_code": code,
        "kdv_haric_tavsiye_edilen_perakende_fiyat": None,
        "kdv_haric_net_fiyat": None,
        "kdv_haric_satis_fiyati": None,
        "stok_durumu": f"HATA: {error_msg}",
        "stock_amount": None,
        "minimum_alis_fiyati": None,
        "minimum_alis_carpi_kdv_haric_satis": None,
    }


def process_product_with_resilience(code, cookie_manager):
    """
    Process a single product with resilience against:
    - transient rate limits (retry with backoff),
    - expired cookies (single global refresh).
    """
    global processed_count, rate_limit_errors

    url = f"{BASE_PRODUCT_URL}?SKU={code.replace('.', '')}&ProductQuantity=20000"

    # jitter to avoid burst rate limiting across threads
    time.sleep(REQUEST_DELAY + random.uniform(0, 0.8))

    retries = 0
    did_global_refresh = False

    while retries <= MAX_RATE_LIMIT_RETRIES:
        retries += 1
        session_cookies = cookie_manager.get_available_session()
        if not session_cookies:
            return create_error_result(code, "No available cookie sessions")

        try:
            data = retrieve_product_data(url=url, cookie_information=session_cookies)

            if hit_rate_limited(data):
                rate_limit_errors += 1
                # gentle backoff, don't refresh cookies for rate limit
                time.sleep(RATE_LIMIT_RETRY_DELAY + random.uniform(0, 0.5))
                continue

            if looks_unauthorized(data):
                if not did_global_refresh:
                    did_global_refresh = cookie_manager.refresh_all_sessions()
                    if did_global_refresh:
                        # retry immediately with fresh cookies
                        continue
                # if refresh already done or failed:
                return create_error_result(code, "Unauthorized after refresh")

            # normal path
            satis_fiyati = parse_price(data.get("kdv_haric_satis_fiyati"))
            min_alis = data.get("minimum_alis_fiyati")
            raw_stok_durumu = data.get("stok_durumu")
            stok_durumu = "Stok verisi yok" if (raw_stok_durumu is None or str(raw_stok_durumu).strip() == "") else raw_stok_durumu

            result = {
                "stock_code": code,
                "kdv_haric_tavsiye_edilen_perakende_fiyat": data.get("kdv_haric_tavsiye_edilen_perakende_fiyat"),
                "kdv_haric_net_fiyat": data.get("kdv_haric_net_fiyat"),
                "kdv_haric_satis_fiyati": data.get("kdv_haric_satis_fiyati"),
                "stok_durumu": stok_durumu,
                "stock_amount": data.get("stock_amount"),
                "minimum_alis_fiyati": data.get("minimum_alis_fiyati"),
                "minimum_alis_carpi_kdv_haric_satis": (
                    satis_fiyati * int(min_alis)
                    if satis_fiyati is not None and min_alis is not None
                    else None
                )
            }

            with progress_lock:
                global processed_count
                processed_count += 1
                print(f"✅ [{processed_count}/{total_count}] Completed: {code}")

            return result

        except Exception as e:
            # network or parsing issue — back off and try again a bit
            if retries <= MAX_RATE_LIMIT_RETRIES:
                time.sleep(RATE_LIMIT_RETRY_DELAY + random.uniform(0, 0.5))
                continue
            return create_error_result(code, f"Exception: {e}")

    return create_error_result(code, "Exceeded max retries")


def process_batch(product_batch, cookie_manager):
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_code = {
            executor.submit(process_product_with_resilience, code, cookie_manager): code
            for code in product_batch
        }
        for future in as_completed(future_to_code):
            code = future_to_code[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                results.append(create_error_result(code, f"Exception in future: {e}"))
    return results


# -------------------- Main --------------------

def main():
    global processed_count, total_count, rate_limit_errors

    informal_mail = os.getenv("informal_mail")
    excel_mail = os.getenv("gmail_receiver_email")
    try:
        st = time.time()

        # Initialize cookie manager: one login, open 5 tabs, quit driver, reuse cookies
        cookie_manager = CookieManager(max_sessions=MAX_WORKERS)
        if not cookie_manager.cookie_sessions:
            print("❌ No cookie sessions available. Cannot proceed with scraping.")
            return

        print(f"📥 Reading product codes from {INPUT_FILE}")
        df_input = pd.read_excel(INPUT_FILE)

        codes = df_input.iloc[:, 0].dropna().astype(str).tolist()
        total_count = len(codes)
        print(f"🔁 Scraping {total_count} products with {MAX_WORKERS} workers...")

        send_mail_without_excel(informal_mail, content=f"{total_count} urunun web kazima islemi baslatildi (multithreaded).")

        all_results = []

        for i in range(0, len(codes), BATCH_SIZE):
            batch = codes[i:i + BATCH_SIZE]
            batch_num = (i // BATCH_SIZE) + 1
            total_batches = (len(codes) + BATCH_SIZE - 1) // BATCH_SIZE

            print(f"\n📦 Processing batch {batch_num}/{total_batches} ({len(batch)} products)")
            batch_results = process_batch(batch, cookie_manager)
            all_results.extend(batch_results)

            progress = (len(all_results) / total_count) * 100
            print(f"📊 Overall progress: {progress:.1f}% ({len(all_results)}/{total_count})")

            if rate_limit_errors > 0:
                print(f"⚠️ Rate limit errors so far: {rate_limit_errors}")

            if i + BATCH_SIZE < len(codes):
                time.sleep(BATCH_DELAY)

        df_out = pd.DataFrame(all_results)
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        df_out.to_excel(OUTPUT_FILE, index=False)
        print(f"\n✅ Done. Saved results to {OUTPUT_FILE}")

        send_mail_without_excel(recipient_email=informal_mail)
        send_mail_with_excel(excel_mail, OUTPUT_FILE)

        et = time.time()
        duration = round((et - st) / 60, 2)
        print(f"Time took to scrape {total_count} products: {duration} minutes.")
        print(f"Rate limit errors encountered: {rate_limit_errors}")

    except Exception as e:
        try:
            send_mail_without_excel(
                informal_mail,
                content=f"Web kazima islemi hata verdi. Hicbir urunun verisi elde edinemedi. Hata: {e}"
            )
        except Exception:
            pass
        print(f"❌ Fatal error: {e}")


if __name__ == "__main__":
    main()
