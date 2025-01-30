import os

from flask import Flask, redirect, request, session, url_for
import secrets
import requests

app = Flask(__name__)
app.secret_key = "supersecretkey"  # Güvenlik için güçlü bir secret key kullan

# IdeaSoft OAuth Bilgileri
CLIENT_ID = os.getenv('ideasoft_client_id')
CLIENT_SECRET = os.getenv('ideasoft_client_secret')
REDIRECT_URI = os.getenv('ideasoft_redirect_uri')
AUTH_URL = os.getenv('auth_url')
TOKEN_URL = os.getenv('token_url')


@app.route("/")
def index():
    return "OAuth 2.0 Authentication Example for IdeaSoft API"


# 1. Kullanıcıyı yetkilendirme sayfasına yönlendir
@app.route("/login")
def login():
    state = secrets.token_urlsafe(16)  # Rastgele state oluştur
    session["oauth_state"] = state  # State değerini session içinde sakla

    auth_url = (
        f"{AUTH_URL}?"
        f"client_id={CLIENT_ID}&"
        f"response_type=code&"
        f"state={state}&"
        f"redirect_uri={REDIRECT_URI}"
    )
    return redirect(auth_url)


# 2. Yetkilendirme sonrası callback URL
@app.route("/callback")
def callback():
    received_state = request.args.get("state")
    stored_state = session.get("oauth_state")

    # CSRF saldırısını önlemek için state doğrulaması yap
    if received_state != stored_state:
        return "State mismatch. Possible CSRF attack.", 400

    auth_code = request.args.get("code")
    if not auth_code:
        return "Authorization failed. No code received.", 400

    # 3. Yetkilendirme kodu ile Access Token al
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

    if "access_token" in token_data:
        session["access_token"] = token_data["access_token"]
        return f"Access Token Alındı: {token_data['access_token']}"
    else:
        return f"Token alma başarısız: {token_data}"

if __name__ == "__main__":
    app.run(debug=True)
