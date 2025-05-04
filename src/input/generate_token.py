from request_operations import exchange_code_for_token  # adjust as needed

auth_code = input("Enter the authorization code: ")
access_token = exchange_code_for_token(auth_code)

if access_token:
    print("✅ Token successfully obtained and saved.")
else:
    print("❌ Failed to get token.")
