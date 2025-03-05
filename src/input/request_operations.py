import json
import time
import requests
import os
from dotenv import load_dotenv

# Çevresel değişkenleri yükle
load_dotenv()

TOKEN_URL = os.getenv("token_url")
CLIENT_ID = os.getenv("ideasoft_client_id")
CLIENT_SECRET = os.getenv("ideasoft_client_secret")
REDIRECT_URI = "http://127.0.0.1:5001/callback"
TOKEN_FILE = "token.json"


def load_token():
    """Token bilgisini JSON dosyasından yükler."""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return json.load(f)
    return None


def save_token(token_data):
    """Token bilgisini dosyaya kaydeder."""
    token_data["timestamp"] = time.time()  # Token alındığı zamanı kaydet
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)


def get_auth_code():
    """Kaydedilen yetkilendirme kodunu döndürür."""
    token_data = load_token()
    if token_data and "auth_code" in token_data:
        return token_data["auth_code"]
    print("❌ HATA: Yetkilendirme kodu bulunamadı!")
    return None


def exchange_code_for_token():
    """Yetkilendirme kodu ile access token alır."""
    auth_code = get_auth_code()
    if not auth_code:
        return None

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
        print("✅ Access token başarıyla kaydedildi!")
        return token_data["access_token"]

    print("❌ Access token alınamadı! Hata:", token_data)
    return None


def refresh_access_token():
    """Access token süresi dolunca refresh token ile yeniler."""
    token_data = load_token()
    if not token_data or "refresh_token" not in token_data:
        print("❌ HATA: Refresh token bulunamadı!")
        return None

    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": token_data["refresh_token"],
        },
    )

    new_token_data = response.json()

    if "access_token" in new_token_data:
        save_token(new_token_data)
        print("✅ Access token başarıyla yenilendi!")
        return new_token_data["access_token"]

    print("❌ Token yenileme başarısız:", new_token_data)
    return None


def get_access_token():
    """Geçerli bir access token döndürür, gerekirse yeniler."""
    token_data = load_token()

    if not token_data:
        print("❌ HATA: Token bulunamadı. Yetkilendirmeyi tekrar yapmalısın.")
        return None

    expires_in = int(token_data.get("expires_in", 3600))  # Varsayılan 1 saat
    expiry_time = token_data["timestamp"] + expires_in
    BUFFER_TIME = 300  # 5 dakika öncesinden yenile

    if time.time() > (expiry_time - BUFFER_TIME):
        print("🔄 Access token süresi doluyor, yenileniyor...")
        return refresh_access_token()

    return token_data["access_token"]


if __name__ == "__main__":
    exchange_code_for_token()  # Yetkilendirme kodu alınınca çalıştır.
