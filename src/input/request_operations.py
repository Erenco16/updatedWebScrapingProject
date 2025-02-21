import requests
import json


def get_access_token():
    response = requests.get("http://127.0.0.1:5000/get_token")
    token_data = response.json()
    return token_data["access_token"]


def get_all_products(brand_id):
    url = "https://evan.myideasoft.com/admin-api/products"
    headers = {"Authorization": f"Bearer {get_access_token()}"}
    products = []
    page = 1

    while True:
        params = {"brand": brand_id, "limit": 100, "page": page}
        response = requests.get(url, headers=headers, params=params)
        print(f"Got page {page}")
        if response.status_code != 200:
            print(f"Error: {response.status_code}")
            break

        data = response.json()

        if not data:  # if data returns empty, then that's all
            break

        products.extend(item['sku'] for item in data if 'sku' in item)
        page += 1  # go to next page

    return products


if __name__ == "__main__":
    brand_id = 38
    all_skus = get_all_products(brand_id)

    print(json.dumps(all_skus, indent=4, ensure_ascii=False))
