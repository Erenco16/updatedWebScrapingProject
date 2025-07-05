import os
import sys
import pandas as pd

# Add src directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

# Constants (same as in main.py)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../src/core'))
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
INPUT_FILE = os.path.join(ROOT_DIR, "input", "product_codes.xlsx")

def get_first_1000_products():
    """Get the first 1000 product codes from the Excel file"""
    try:
        print(f"📥 Reading product codes from {INPUT_FILE}")
        df_input = pd.read_excel(INPUT_FILE)
        
        # Get all codes (same logic as main.py)
        all_codes = df_input.iloc[:, 0].dropna().astype(str).tolist()
        print(f"📊 Total products found: {len(all_codes)}")
        
        # Get first 1000 products
        first_1000 = all_codes[:1000]
        print(f"🎯 First 1000 products extracted: {len(first_1000)}")
        
        # Show first 10 products as example
        print(f"\n📋 First 10 products:")
        for i, code in enumerate(first_1000[:10], 1):
            print(f"  {i:3d}. {code}")
        
        if len(first_1000) > 10:
            print(f"  ... and {len(first_1000) - 10} more products")
        
        return first_1000
        
    except Exception as e:
        print(f"❌ Error reading product codes: {e}")
        return []

def save_first_1000_to_file():
    """Save the first 1000 products to a new file"""
    first_1000 = get_first_1000_products()
    
    if first_1000:
        # Create a DataFrame with the first 1000 products
        df_first_1000 = pd.DataFrame({'Product_Code': first_1000})
        
        # Save to Excel file
        output_file = os.path.join(os.path.dirname(__file__), "first_1000_products.xlsx")
        df_first_1000.to_excel(output_file, index=False)
        print(f"\n💾 First 1000 products saved to: {output_file}")
        
        return output_file
    else:
        print("❌ No products to save")
        return None

def main():
    print("🚀 Getting first 1000 products from product_codes.xlsx...")
    
    # Get and display first 1000 products
    first_1000 = get_first_1000_products()
    
    if first_1000:
        # Ask if user wants to save to file
        save_choice = input("\n💾 Do you want to save the first 1000 products to a file? (y/n): ").strip().lower()
        
        if save_choice in ['y', 'yes']:
            output_file = save_first_1000_to_file()
            if output_file:
                print(f"✅ Successfully saved first 1000 products to: {output_file}")
        else:
            print("📝 Products not saved to file")
    
    print("\n🎉 Done!")

if __name__ == "__main__":
    main() 