import os
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time
import urllib.parse
import requests
from pathlib import Path


# Load environment variables from .env file
load_dotenv()

TOKEN_URL = os.getenv("TOKEN_URL")
CLIENT_ID = os.getenv("ideasoft_client_id")
CLIENT_SECRET = os.getenv("ideasoft_client_secret")

# Buffer before token expiry (seconds)
BUFFER_TIME = 300


def update_env_variable(key, value, env_file=".env"):
    path = Path(env_file)
    if not path.exists():
        path.write_text(f"{key}={value}\n")
        return

    lines = path.read_text().splitlines()
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            updated = True
            break

    if not updated:
        lines.append(f"{key}={value}")

    path.write_text("\n".join(lines) + "\n")


def automate_oauth_flow():
    response = requests.get("http://127.0.0.1:5001/get_auth_url")
    auth_url = response.json()["auth_url"]

    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"user-agent={os.getenv('USER_AGENT', 'Mozilla/5.0')}")

    selenium_hub_url = os.getenv("GRID_URL", "http://selenium:4444/wd/hub")
    driver = webdriver.Remote(command_executor=selenium_hub_url, options=options)

    try:
        driver.get(auth_url)
        time.sleep(10)

        current_url = driver.current_url
        parsed_url = urllib.parse.urlparse(current_url)
        query = urllib.parse.parse_qs(parsed_url.query)
        auth_code = query.get("code", [None])[0]

        if auth_code:
            print(f"✅ Got auth code: {auth_code}")

            callback_response = requests.get(
                f"http://localhost:5001/callback?code={auth_code}"
            )
            token_response = callback_response.json()

            if "token" in token_response:
                token_data = token_response["token"]
                access_token = token_data["access_token"]
                refresh_token = token_data["refresh_token"]
                expires_in = token_data.get("expires_in", 86400)
                timestamp = str(int(time.time()))

                update_env_variable("ACCESS_TOKEN", access_token)
                update_env_variable("REFRESH_TOKEN", refresh_token)
                update_env_variable("EXPIRES_IN", str(expires_in))
                update_env_variable("TOKEN_TIMESTAMP", timestamp)

                print("✅ Auth flow completed and tokens saved.")
                return access_token

            print("❌ Token not found in callback response:", token_response)
        else:
            print("❌ Failed to capture authorization code.")

        return None
    finally:
        driver.quit()


def get_access_token():
    """
    Returns a valid access token. If the token is near expiration,
    it refreshes it using the refresh token.
    """
    token_timestamp = float(os.getenv("TOKEN_TIMESTAMP", "0"))
    expires_in = int(os.getenv("EXPIRES_IN", "86400"))
    expiry_time = token_timestamp + expires_in

    if time.time() > (expiry_time - BUFFER_TIME):
        print("🔄 Access token is expiring, attempting to refresh...")
        return refresh_access_token()

    return os.getenv("ACCESS_TOKEN")

def refresh_access_token():
    refresh_token = os.getenv("REFRESH_TOKEN")

    if not refresh_token:
        print("❌ ERROR: Refresh token not found. Reauthorization needed.")
        return automate_oauth_flow()

    print("🔄 Requesting new access token using refresh token...")

    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": refresh_token
        }
    )

    if response.status_code != 200:
        print("❌ Token refresh failed:", response.text)
        print("🔁 Attempting full re-authorization via browser...")
        return automate_oauth_flow()

    new_token_data = response.json()

    if "access_token" in new_token_data and "refresh_token" in new_token_data:
        access_token = new_token_data["access_token"]
        refresh_token = new_token_data["refresh_token"]
        expires_in = new_token_data.get("expires_in", 86400)
        timestamp = str(int(time.time()))

        # Save to .env
        update_env_variable("ACCESS_TOKEN", access_token)
        update_env_variable("REFRESH_TOKEN", refresh_token)
        update_env_variable("EXPIRES_IN", str(expires_in))
        update_env_variable("TOKEN_TIMESTAMP", timestamp)

        print("✅ Token refreshed and saved to .env")
        return access_token

    print("❌ Unexpected response format:", new_token_data)
    return None


def load_tokens():
    """Load token data from environment variables."""
    return {
        "access_token": os.getenv("ACCESS_TOKEN"),
        "refresh_token": os.getenv("REFRESH_TOKEN"),
        "token_timestamp": os.getenv("TOKEN_TIMESTAMP"),
        "expires_in": os.getenv("EXPIRES_IN")
    }

def save_tokens(access_token, refresh_token):
    """
    Placeholder for saving tokens securely.
    Use this if you implement a secure storage solution.
    """
    pass
