import os
import time
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

TOKEN_URL = os.getenv("TOKEN_URL")
CLIENT_ID = os.getenv("ideasoft_client_id")
CLIENT_SECRET = os.getenv("ideasoft_client_secret")

# Buffer before token expiry (seconds)
BUFFER_TIME = 300

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
    """
    Uses the refresh token to obtain a new access token.
    This assumes you will update the .env file manually or via a secure secrets manager.
    """
    refresh_token = os.getenv("REFRESH_TOKEN")

    if not refresh_token:
        print("❌ ERROR: Refresh token not found. Reauthorization needed.")
        return None

    print("🔄 Requesting new access token using refresh token...")

    response = requests.get(
        f"{TOKEN_URL}?grant_type=refresh_token"
        f"&client_id={CLIENT_ID}"
        f"&client_secret={CLIENT_SECRET}"
        f"&refresh_token={refresh_token}"
    )

    print(f"Sending a request to this url: {response.url}")
    if response.status_code != 200:
        print("❌ Token refresh failed:", response.text)
        return None

    new_token_data = response.json()

    if "access_token" in new_token_data and "refresh_token" in new_token_data:
        print("✅ Token refreshed successfully!")
        return new_token_data["access_token"]

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
