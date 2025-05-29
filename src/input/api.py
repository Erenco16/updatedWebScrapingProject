import requests
from token_manager import get_access_token
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed


def get_total_pages(brand_id, access_token):
    url = "https://evan.myideasoft.com/admin-api/products"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"brand": brand_id, "limit": 100, "page": 1}

    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        print(f"❌ Hata: {response.status_code}, {response.text}")
        return 0

    total_count = response.headers.get("total_count")
    if total_count is None:
        print("❌ 'total_count' başlığı bulunamadı.")
        return 0

    try:
        total_count = int(total_count)
        total_pages = (total_count // 100) + (1 if total_count % 100 else 0)
        return total_pages
    except ValueError:
        print("❌ 'total_count' değeri sayıya çevrilemedi:", total_count)
        return 0


def fetch_page(brand_id, page, access_token):
    url = "https://evan.myideasoft.com/admin-api/products"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"brand": brand_id, "limit": 100, "page": page}

    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        print(f"❌ Hata (sayfa {page}): {response.status_code}, {response.text}")
        return []

    data = response.json()
    skus = [item["sku"] for item in data if "sku" in item]
    print(f"📦 Sayfa {page} yüklendi. Ürün Sayısı: {len(skus)}")
    return skus

def get_all_products(brand_id):
    """Belirtilen marka ID'ye göre tüm ürünleri getirir (multithreaded sayfalandırma ile)."""
    access_token = get_access_token()
    if not access_token:
        print("❌ API çağrısı yapılamadı: Geçerli access token bulunamadı.")
        return None

    total_pages = get_total_pages(brand_id, access_token)
    if total_pages == 0:
        return []

    all_skus = []
    with ThreadPoolExecutor(max_workers=50) as executor:
        future_to_page = {
            executor.submit(fetch_page, brand_id, page, access_token): page
            for page in range(1, total_pages + 1)
        }

        for future in as_completed(future_to_page):
            page = future_to_page[future]
            try:
                skus = future.result()
                all_skus.extend(skus)
            except Exception as e:
                print(f"⚠️ Hata (sayfa {page}): {e}")

    print(f"✅ Tüm ürünler çekildi. Toplam SKU: {len(all_skus)}")
    return all_skus

def write_to_excel(skus, file_name="product_codes.xlsx"):
    """SKU bilgilerini Excel dosyasına kaydeder."""
    df = pd.DataFrame(skus, columns=["stockCode"])  # SKU'ları DataFrame'e çevir
    df.to_excel(file_name, index=False)  # Excel dosyasına yaz
    print(f"✅ SKU'lar {file_name} dosyasına kaydedildi.")

def refresh_token_on_start():
    """
    Forces an access token refresh when the script starts.
    Useful for ensuring the token is valid before any requests are made.
    """
    from token_manager import refresh_access_token

    print("🔁 Başlangıçta access token yenileniyor...")
    new_token = refresh_access_token()

    if not new_token:
        print("❌ Token yenileme başarısız. Devam edilemiyor.")
        exit(1)
    print("✅ Başarılı bir şekilde yenilendi ve kullanılmaya hazır.")


# **Marka ID'sini girerek API'den tüm ürünleri çek ve Excel'e yaz!**
if __name__ == "__main__":
    refresh_token_on_start()
    brand_id = 38  # İlgili markanın ID'si
    skus = get_all_products(brand_id)

    if skus:
        write_to_excel(skus)
