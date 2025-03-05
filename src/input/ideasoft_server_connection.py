from flask import Flask, request, jsonify
import json
import time
import os

app = Flask(__name__)

TOKEN_FILE = "token.json"


def save_auth_code(auth_code):
    """Yetkilendirme kodunu JSON dosyasına kaydeder."""
    data = {"auth_code": auth_code, "timestamp": time.time()}
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f)


@app.route("/")
def home_page():
    return "Flask server is running for Ideasoft API authentication"


@app.route("/callback")
def callback():
    """Yetkilendirme kodunu alır ve kaydeder."""
    auth_code = request.args.get("code")

    if not auth_code:
        return "Yetkilendirme kodu alınamadı.", 400

    save_auth_code(auth_code)
    print(f"✅ Yetkilendirme kodu alındı: {auth_code}")
    return "Yetkilendirme başarılı! Artık access token alınabilir."


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
