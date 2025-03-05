import secrets
import os
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("ideasoft_client_id")
CLIENT_SECRET = os.getenv("ideasoft_client_secret")
REDIRECT_URI = "http://127.0.0.1:5001/callback"
AUTH_URL = os.getenv("auth_url")
TOKEN_URL = os.getenv("token_url")

def main():

    state = secrets.token_urlsafe(16)  # Rastgele güvenli bir state oluştur

    auth_url = (
        f"{AUTH_URL}?"
        f"client_id={CLIENT_ID}&"
        f"response_type=code&"
        f"state={state}&"
        f"scope=product_read&"
        f"redirect_uri={REDIRECT_URI}"
    )

    print(f"Auth url (Access from the browser):\n{auth_url}")

if __name__ == "__main__":
    main()