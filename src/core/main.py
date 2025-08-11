import os
import sys
import pickle
import pandas as pd
from dotenv import load_dotenv
import threading
from datetime import datetime
import time
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
import requests

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

# Load env
load_dotenv()

# Import project functions
from scraper.scraping_functions import retrieve_product_data
from scraper.send_mail import send_mail_without_excel, send_mail_with_excel
from hafele_login.handle_login import handle_login
from core.config import *
import random

# Constants
BASE_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
INPUT_FILE = os.path.join(ROOT_DIR, "input", "product_codes.xlsx")
OUTPUT_FILE = os.path.join(ROOT_DIR, "output", "product_data_results.xlsx")
COOKIE_FILE = os.path.join(ROOT_DIR, "shared", "cookies.pkl")
BASE_PRODUCT_URL = f"{Hafele_BASE_URL}{Hafele_PRODUCT_API_PATH}"

# Global state
cookies = None
cookie_lock = threading.Lock()
progress_lock = threading.Lock()
processed_count = 0
total_count = 0
rate_limit_errors = 0


class CookieManager:
    """Simplified cookie manager with better error handling"""
    
    def __init__(self, max_sessions=MAX_SESSIONS):
        self.max_sessions = max_sessions
        self.cookie_sessions = []
        self.session_lock = threading.Lock()
        self.initialize_sessions()
    
    def initialize_sessions(self):
        """Initialize cookie sessions with better error handling"""
        print(f"🔄 Initializing {self.max_sessions} cookie sessions...")
        
        # First, try to load existing cookies
        if os.path.exists(COOKIE_FILE):
            try:
                with open(COOKIE_FILE, "rb") as f:
                    existing_cookies = pickle.load(f)
                self.cookie_sessions.append({
                    'cookies': existing_cookies,
                    'last_used': time.time(),
                    'error_count': 0,
                    'source': 'file'
                })
                print("✅ Loaded existing cookies from file")
            except Exception as e:
                print(f"⚠️ Failed to load existing cookies: {e}")
        
        # If we don't have enough sessions, try to create new ones
        while len(self.cookie_sessions) < self.max_sessions:
            try:
                print(f"🔄 Creating new session {len(self.cookie_sessions) + 1}...")
                driver = handle_login()
                session_cookies = driver.get_cookies()
                driver.quit()
                
                self.cookie_sessions.append({
                    'cookies': session_cookies,
                    'last_used': time.time(),
                    'error_count': 0,
                    'source': 'new'
                })
                print(f"✅ Session {len(self.cookie_sessions)} created successfully")
                
                # Save the new cookies
                try:
                    os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)
                    with open(COOKIE_FILE, "wb") as f:
                        pickle.dump(session_cookies, f)
                    print("💾 New cookies saved to file")
                except Exception as e:
                    print(f"⚠️ Failed to save cookies: {e}")
                
                time.sleep(3)  # Delay between logins
                
            except Exception as e:
                print(f"❌ Failed to create session {len(self.cookie_sessions) + 1}: {e}")
                break  # Stop trying if we can't create any more sessions
        
        if not self.cookie_sessions:
            print("❌ No cookie sessions available")
        else:
            print(f"✅ Cookie manager initialized with {len(self.cookie_sessions)} sessions")
    
    def validate_session(self, cookies):
        """Simplified session validation - just check if cookies exist and have values"""
        if not cookies:
            return False
        
        # Check if we have essential cookies
        essential_cookies = ['JSESSIONID', 'BIGipServer', 'ASP.NET_SessionId']
        cookie_names = [cookie.get('name', '') for cookie in cookies]
        
        # If we have any essential cookies, consider it valid
        has_essential = any(name in cookie_names for name in essential_cookies)
        
        if not has_essential:
            print("⚠️ No essential cookies found in session")
            return False
        
        return True

    def get_available_session(self):
        """Get an available session with simplified logic"""
        with self.session_lock:
            if not self.cookie_sessions:
                print("❌ No cookie sessions available")
                return None
            
            # Get the least recently used session
            session = min(self.cookie_sessions, key=lambda x: x['last_used'])
            
            # Simple validation - just check if cookies exist
            if not self.validate_session(session['cookies']):
                print("🔄 Session validation failed, trying to refresh...")
                if not self.refresh_session(session):
                    return None
            
            session['last_used'] = time.time()
            return session['cookies']
    
    def refresh_session(self, session):
        """Refresh a session by creating a new login"""
        try:
            print("🔄 Refreshing session...")
            driver = handle_login()
            new_cookies = driver.get_cookies()
            driver.quit()
            
            session['cookies'] = new_cookies
            session['error_count'] = 0
            session['last_used'] = time.time()
            session['source'] = 'refreshed'
            
            # Save the refreshed cookies
            try:
                with open(COOKIE_FILE, "wb") as f:
                    pickle.dump(new_cookies, f)
                print("💾 Refreshed cookies saved to file")
            except Exception as e:
                print(f"⚠️ Failed to save refreshed cookies: {e}")
            
            print("✅ Session refreshed successfully")
            return True
            
        except Exception as e:
            print(f"❌ Failed to refresh session: {e}")
            session['error_count'] += 1
            return False
    
    def mark_session_error(self, cookies):
        """Mark a session as having an error"""
        with self.session_lock:
            for session in self.cookie_sessions:
                if session['cookies'] == cookies:
                    session['error_count'] += 1
                    print(f"⚠️ Session error count: {session['error_count']}")
                    
                    if session['error_count'] >= 2:  # Reduced threshold
                        print("🔄 Too many errors, refreshing session...")
                        self.refresh_session(session)
                    break


# Removed the old refresh_cookies function as it's now handled by CookieManager


# Removed the old load_initial_cookies function as it's now handled by CookieManager


def parse_price(price_str):
    """Parse price string to float"""
    if price_str is None:
        return None

    # Clean the string
    cleaned = price_str.replace(".", "").replace(",", ".")

    # Check if it's a valid float
    try:
        return float(cleaned)
    except ValueError:
        return None


def process_product_with_rate_limiting(code, cookie_manager):
    """Process a single product with rate limiting and error handling"""
    global processed_count, rate_limit_errors
    
    url = f"{BASE_PRODUCT_URL}?SKU={code.replace('.', '')}&ProductQuantity=20000"
    
    # Get available cookie session
    session_cookies = cookie_manager.get_available_session()
    if not session_cookies:
        print(f"❌ No available cookie sessions for {code}")
        return create_error_result(code, "No available cookie sessions")
    
    # Add random delay to avoid rate limiting
    time.sleep(REQUEST_DELAY + random.uniform(0, 1))
    
    try:
        data = retrieve_product_data(url, session_cookies)
        
        # Check if we got rate limited
        if data.get("stok_durumu") == "Rate limit exceeded" or "rate limit" in str(data).lower():
            rate_limit_errors += 1
            cookie_manager.mark_session_error(session_cookies)
            print(f"⚠️ Rate limit hit for {code}, retrying with delay...")
            time.sleep(RATE_LIMIT_RETRY_DELAY)
            return process_product_with_rate_limiting(code, cookie_manager)
        
        satis_fiyati = parse_price(data.get("kdv_haric_satis_fiyati"))
        min_alis = data.get("minimum_alis_fiyati")
        
        # Conditionally determine stock status
        raw_stok_durumu = data.get("stok_durumu")
        if raw_stok_durumu is None or str(raw_stok_durumu).strip() == "":
            stok_durumu = "Stok verisi yok"
        else:
            stok_durumu = raw_stok_durumu
        
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
        
        # Update progress
        with progress_lock:
            processed_count += 1
            print(f"✅ [{processed_count}/{total_count}] Completed: {code}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error processing product {code}: {e}")
        cookie_manager.mark_session_error(session_cookies)
        return create_error_result(code, str(e))


def create_error_result(code, error_msg):
    """Create a standardized error result"""
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


def process_batch(product_batch, cookie_manager):
    """Process a batch of products using ThreadPoolExecutor"""
    results = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all products in the batch
        future_to_code = {
            executor.submit(process_product_with_rate_limiting, code, cookie_manager): code 
            for code in product_batch
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_code):
            code = future_to_code[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                print(f"❌ Exception for {code}: {e}")
                results.append(create_error_result(code, str(e)))
    
    return results


def main():
    global processed_count, total_count
    
    informal_mail = os.getenv("informal_mail")
    try:
        st = time.time()
        
        # Initialize cookie manager for multithreading
        cookie_manager = CookieManager(max_sessions=MAX_WORKERS)
        
        # Check if we have any working sessions
        if not cookie_manager.cookie_sessions:
            print("❌ No cookie sessions available. Cannot proceed with scraping.")
            return

        print(f"📥 Reading product codes from {INPUT_FILE}")
        df_input = pd.read_excel(INPUT_FILE)
        
        # Randomly pick 100 rows
        if len(df_input) > 10:
            df_input = df_input.sample(n=10, random_state=42)  # random_state for reproducibility
            print(f"🎲 Randomly selected 10 rows from {len(df_input)} total rows")
        
        codes = df_input.iloc[:, 0].dropna().astype(str).tolist()
        total_count = len(codes)
        print(f"🔁 Scraping {total_count} products with {MAX_WORKERS} workers...")

        send_mail_without_excel(informal_mail, content=f"{total_count} urunun web kazima islemi baslatildi (multithreaded).")

        all_results = []
        
        # Process products in batches
        for i in range(0, len(codes), BATCH_SIZE):
            batch = codes[i:i + BATCH_SIZE]
            batch_num = (i // BATCH_SIZE) + 1
            total_batches = (len(codes) + BATCH_SIZE - 1) // BATCH_SIZE
            
            print(f"\n📦 Processing batch {batch_num}/{total_batches} ({len(batch)} products)")
            batch_results = process_batch(batch, cookie_manager)
            all_results.extend(batch_results)
            
            # Progress update
            progress = (len(all_results) / total_count) * 100
            print(f"📊 Overall progress: {progress:.1f}% ({len(all_results)}/{total_count})")
            
            # Rate limit monitoring
            if rate_limit_errors > 0:
                print(f"⚠️ Rate limit errors so far: {rate_limit_errors}")
            
            # Small delay between batches
            if i + BATCH_SIZE < len(codes):
                print("⏳ Waiting between batches...")
                time.sleep(BATCH_DELAY)

        df_out = pd.DataFrame(all_results)
        df_out.to_excel(OUTPUT_FILE, index=False)
        print(f"\n✅ Done. Saved results to {OUTPUT_FILE}")
        # Send completion email
        # send_mail_without_excel(informal_mail, content="Web kazima islemi basariyla tamamlandi")
        send_mail_with_excel(informal_mail, OUTPUT_FILE)
        # send_mail_with_excel(os.getenv("gmail_receiver_email"), OUTPUT_FILE)
        # send_mail_with_excel(os.getenv("gmail_receiver_email_2"), OUTPUT_FILE)


        et = time.time()
        duration = round((et - st) / 60, 2)
        print(f"Time took to scrape {total_count} products: {duration} minutes.")
        print(f"Rate limit errors encountered: {rate_limit_errors}")

    except Exception as e:
        send_mail_without_excel(informal_mail,
                                content=f"Web kazima islemi hata verdi. Hicbir urunun verisi edinelemedi. Hata: {e}")


if __name__ == "__main__":
    main()