import requests
from token_manager import get_access_token
import pandas as pd


def get_all_products(brand_id):
    """Belirtilen marka ID'ye göre tüm ürünleri getirir (sayfalandırma ile)."""
    access_token = get_access_token()  # 🔥 Yeni Access Token Yönetimi Burada Kullanılıyor!

    if not access_token:
        print("❌ API çağrısı yapılamadı: Geçerli access token bulunamadı.")
        return None

    headers = {"Authorization": f"Bearer {access_token}"}
    url = "https://evan.myideasoft.com/admin-api/products"

    all_skus = []
    page = 1

    while True:
        params = {"brand": brand_id, "limit": 100, "page": page}
        response = requests.get(url, headers=headers, params=params)

        if response.status_code != 200:
            print(f"❌ Hata: {response.status_code}, {response.text}")
            break

        data = response.json()
        if not data:
            print("✅ Tüm ürünler çekildi.")
            break

        skus = [item["sku"] for item in data if "sku" in item]
        all_skus.extend(skus)

        print(f"📦 Sayfa {page} yüklendi. Ürün Sayısı: {len(skus)}")

        if len(skus) < 100:
            print("✅ Son sayfa alındı, işlem tamamlandı.")
            break

        page += 1

    return all_skus

def write_to_excel(skus, file_name="product_codes.xlsx"):
    """SKU bilgilerini Excel dosyasına kaydeder."""
    df = pd.DataFrame(skus, columns=["stockCode"])  # SKU'ları DataFrame'e çevir
    df.to_excel(file_name, index=False)  # Excel dosyasına yaz
    print(f"✅ SKU'lar {file_name} dosyasına kaydedildi.")

# **Marka ID'sini girerek API'den tüm ürünleri çek ve Excel'e yaz!**
if __name__ == "__main__":
    brand_id = 38  # İlgili markanın ID'si
    skus = get_all_products(brand_id)

    if skus:
        write_to_excel(skus)
