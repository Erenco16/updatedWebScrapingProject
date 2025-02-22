import os
import time
import json
import requests
import secrets
from flask import Flask, session

app = Flask(__name__)
app.secret_key = "supersecretkey"

# OAuth Configuration
CLIENT_ID = os.getenv("ideasoft_client_id")
CLIENT_SECRET = os.getenv("ideasoft_client_secret")
REDIRECT_URI = os.getenv("ideasoft_redirect_uri")
AUTH_URL = os.getenv("auth_url")
TOKEN_URL = os.getenv("token_url")

# Token Storage File
TOKEN_FILE = "token.json"


def save_token(token_data):
    """Save token data to a JSON file"""
    token_data["timestamp"] = time.time()  # Store the timestamp when received
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)


def load_token():
    """Load token data from a JSON file"""
    TOKEN_FILE = "/app/src/input/token.json"

    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                token_data = json.load(f)
                print(f"LOADED TOKEN: {token_data}")  # Debug için
                return token_data
        except json.JSONDecodeError as e:
            print(f"Error loading token.json: {e}")
            return None
    return None


def refresh_access_token(refresh_token):
    """Automatically refresh the access token when expired"""
    print("Refreshing token...")

    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": refresh_token,
        },
    )

    token_data = response.json()
    print("Refresh Token Response:", token_data)

    if "access_token" in token_data:
        save_token(token_data)
        return token_data["access_token"]

    return None


def automate_login():
    """Fully automate the OAuth login process"""
    # Step 1: Generate the authentication URL
    state = secrets.token_urlsafe(16)

    auth_url = (
        f"{AUTH_URL}?"
        f"client_id={CLIENT_ID}&"
        f"response_type=code&"
        f"state={state}&"
        f"scope=product_read&"
        f"redirect_uri={REDIRECT_URI}"
    )
    # Step 2: Simulate a user visiting the authorization URL
    with requests.Session() as s:
        response = s.get(auth_url, allow_redirects=True)

        # Step 3: Extract the authorization code from the redirected URL
        if response.history:
            final_url = response.url  # This should be the redirected URL with the code

            # Extract the authorization code from the URL
            from urllib.parse import urlparse, parse_qs
            parsed_url = urlparse(final_url)
            auth_code = parse_qs(parsed_url.query).get("code", [None])[0]

            if auth_code:
                return exchange_code_for_token(auth_code)
    return None


def exchange_code_for_token(auth_code):
    """Exchange the authorization code for an access token"""
    token_response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
        },
    )

    token_data = token_response.json()
    print("Token Response:", token_data)

    if "access_token" in token_data:
        save_token(token_data)
        return token_data["access_token"]

    return None


@app.route("/get_token")
def get_token():
    """Retrieve a valid access token, refreshing or logging in automatically if needed"""
    token_data = load_token()

    if token_data:
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expiry_time = token_data.get("timestamp", 0) + token_data.get("expires_in", 0)

        print(f"DEBUG: Loaded token data -> {token_data}")  # Debug için
        print(f"DEBUG: Current time -> {time.time()} | Expiry time -> {expiry_time}")

        if time.time() > expiry_time and refresh_token:
            print("Access token expired. Refreshing...")
            access_token = refresh_access_token(refresh_token)

        if access_token:
            return {"access_token": access_token}

    print("No valid token found. Automating login...")
    return {"access_token": automate_login()}



@app.route("/")
def home_page():
    return "Flask web server is running now. This server is created for Ideasoft api connection purposes"

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
