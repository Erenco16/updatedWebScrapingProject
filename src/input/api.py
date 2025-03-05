import requests
from request_operations import get_access_token

def get_all_products(brand_id):
    """Belirtilen marka ID'ye göre tüm ürünleri getirir."""
    access_token = get_access_token()
    if not access_token:
        print("❌ API çağrısı yapılamadı: Geçerli access token bulunamadı.")
        return None

    headers = {"Authorization": f"Bearer {access_token}"}
    url = "https://evan.myideasoft.com/admin-api/products"
    params = {"brand": brand_id, "limit": 100, "page": 1}

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        print("✅ Ürünler başarıyla çekildi.")
        return response.json()

    print(f"❌ Hata: {response.status_code}, {response.text}")
    return None

# **Marka ID'sini girerek API'den ürünleri çek!**
if __name__ == "__main__":
    print(get_all_products(38))
