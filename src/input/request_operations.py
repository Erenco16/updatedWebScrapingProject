import requests
import pandas as pd

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

        if not data:  # If response is empty, stop fetching
            break

        products.extend(item['sku'] for item in data if 'sku' in item)
        page += 1  # Go to next page

    return products

def write_to_excel(skus, file_name="product_codes.xlsx"):
    # Create a DataFrame with a single column 'stockCode'
    df = pd.DataFrame(skus, columns=["stockCode"])

    # Write to Excel, overwrite existing file
    df.to_excel(file_name, index=False)

    print(f"Data written to {file_name}")

if __name__ == "__main__":
    brand_id = 38
    all_skus = get_all_products(brand_id)

    # Write SKUs to Excel file
    write_to_excel(all_skus)
