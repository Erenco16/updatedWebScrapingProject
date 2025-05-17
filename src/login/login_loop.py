import os
import time
import pickle
from login import handle_login

LOCK_FILE = "/shared/login.lock"
COOKIE_FILE = "/shared/cookies.pkl"
DONE_FILE = "/shared/done.flag"
SLEEP_INTERVAL = 480  # 8 minutes

def write_lock():
    with open(LOCK_FILE, "w") as f:
        f.write("locked")

def remove_lock():
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)

print("🔐 Starting initial login...")
driver = None
try:
    driver = handle_login()
    print("✅ Initial login complete.")
except Exception as e:
    print(f"❌ Failed to start login session: {e}")
    exit(1)

# Main refresh loop
while True:
    if os.path.exists(DONE_FILE):
        print("✅ Done flag detected. Closing browser and exiting login loop.")
        break

    print("🔄 Refreshing cookies...")
    write_lock()
    try:
        cookies = driver.get_cookies()
        with open(COOKIE_FILE, "wb") as f:
            pickle.dump(cookies, f)
        print("✅ Cookies refreshed.")
    except Exception as e:
        print(f"❌ Error refreshing cookies: {e}")
    remove_lock()

    for _ in range(SLEEP_INTERVAL // 5):
        if os.path.exists(DONE_FILE):
            print("✅ Done flag detected during sleep. Closing browser.")
            break
        time.sleep(5)

# Final cleanup
if driver:
    try:
        driver.quit()
        print("🧼 Selenium driver quit cleanly.")
    except Exception as e:
        print(f"⚠️ Could not quit driver (likely already closed): {e}")

