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
TOKEN_FILE = "/app/src/input/token.json"


def load_token():
    """Token bilgisini JSON dosyasından yükler."""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return json.load(f)
    return None


def save_token(token_data):
    """Token bilgisini dosyaya kaydeder ve zaman damgası ekler."""
    token_data["timestamp"] = time.time()
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)
    print("✅ Token bilgileri güncellendi.")


def get_access_token():
    """Geçerli bir access token döndürür, gerekirse refresh token ile yeniler."""
    token_data = load_token()

    if not token_data:
        print("❌ HATA: Token bulunamadı! Yeniden yetkilendirme yapmalısın.")
        return None

    expires_in = int(token_data.get("expires_in", 86400))  # 24 saat
    expiry_time = token_data["timestamp"] + expires_in
    BUFFER_TIME = 300  # 5 dakika öncesinden yenile

    # Access Token süresi dolmuşsa yenile
    if time.time() > (expiry_time - BUFFER_TIME):
        print("🔄 Access token süresi doluyor, refresh token kullanılıyor...")
        return refresh_access_token()

    return token_data["access_token"]


def refresh_access_token():
    """Access Token süresi dolduğunda Refresh Token kullanarak yeni bir token alır."""
    token_data = load_token()

    if not token_data or "refresh_token" not in token_data:
        print("❌ HATA: Refresh token bulunamadı! Yeniden yetkilendirme gerekli.")
        return None

    print("🔄 Refresh token ile yeni Access Token alınıyor...")

    response = requests.get(
        f"{TOKEN_URL}?grant_type=refresh_token"
        f"&client_id={CLIENT_ID}"
        f"&client_secret={CLIENT_SECRET}"
        f"&refresh_token={token_data['refresh_token']}"
    )

    new_token_data = response.json()

    if "access_token" in new_token_data and "refresh_token" in new_token_data:
        save_token(new_token_data)
        print("✅ Yeni Access ve Refresh Token alındı!")
        return new_token_data["access_token"]

    print("❌ Token yenileme başarısız:", new_token_data)
    return None
