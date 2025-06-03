import os
import pickle
from hafele_login.handle_login import handle_login

# Absolute path to cookies.pkl relative to project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
COOKIE_PATH = os.path.join(PROJECT_ROOT, "shared", "cookies.pkl")
def get_cookies(force_refresh: bool = False) -> list:
    """
    Load cookies from file or refresh them via login.

    :param force_refresh: If True, forces a new login session.
    :return: List of cookies.
    """
    if os.path.exists(COOKIE_PATH) and not force_refresh:
        try:
            with open(COOKIE_PATH, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            print(f"⚠️ Failed to load cookies, refreshing... ({e})")

    # Refresh cookies by logging in via Selenium
    driver = handle_login()
    cookies = driver.get_cookies()
    driver.quit()

    with open(COOKIE_PATH, "wb") as f:
        pickle.dump(cookies, f)

    return cookies