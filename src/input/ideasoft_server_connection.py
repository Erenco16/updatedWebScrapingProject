import json
import secrets
import time
import requests
import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from pathlib import Path
from token_manager import update_env_variable

app = Flask(__name__)

load_dotenv()

BASE_DIR = os.path.dirname(__file__)
TOKEN_URL = os.getenv("TOKEN_URL")
CLIENT_ID = os.getenv("ideasoft_client_id")
CLIENT_SECRET = os.getenv("ideasoft_client_secret")
REDIRECT_URI = os.getenv("ideasoft_redirect_uri")
TOKEN_FILE = INPUT_FILE = os.path.join(BASE_DIR, "token.json")
AUTH_URL = os.getenv("auth_url")


def save_token(token_data):
    """Token bilgisini dosyaya kaydeder."""
    token_data["timestamp"] = time.time()
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)


def exchange_code_for_token(auth_code):
    """Yetkilendirme kodunu access token'a çevirir."""
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
        },
    )

    token_data = response.json()

    if "access_token" in token_data:
        save_token(token_data)
        print(f"✅ Access token alındı ve kaydedildi!")
        return token_data
    else:
        print(f"❌ Access token alınamadı! Hata: {token_data}")
        return None


@app.route("/callback")
def callback():
    """Yetkilendirme kodunu alır, hemen exchange eder ve token kaydeder."""
    auth_code = request.args.get("code")

    if not auth_code:
        return jsonify({"error": "Yetkilendirme kodu alınamadı."}), 400

    print(f"✅ [DEBUG] Yetkilendirme kodu alındı: {auth_code}")

    # Exchange the code for tokens
    token_data = exchange_code_for_token(auth_code)

    if token_data and "refresh_token" in token_data:
        new_refresh_token = token_data["refresh_token"]

        # ✅ Step 1: Update .env file
        update_env_variable("REFRESH_TOKEN", new_refresh_token)

        # ✅ Step 2: Update current environment variable (optional)
        os.environ["REFRESH_TOKEN"] = new_refresh_token

        return jsonify({"message": "Yetkilendirme başarılı!", "token": token_data}), 200
    else:
        return jsonify({"error": "Access token alınamadı!"}), 400


@app.route("/health")
def health_check():
    """Flask API'nin çalışıp çalışmadığını kontrol eder."""
    return jsonify({"status": "ok"}), 200

@app.route("/get_auth_url")
def return_auth_url():
    state = secrets.token_urlsafe(16)  # generate a random safe state value

    auth_url = (
        f"{AUTH_URL}?"
        f"client_id={CLIENT_ID}&"
        f"response_type=code&"
        f"state={state}&"
        f"scope=product_read&"
        f"redirect_uri={REDIRECT_URI}"
    )
    return jsonify({"auth_url":f"{auth_url}"}), 200


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)