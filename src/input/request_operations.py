import requests
import os
from dotenv import load_dotenv

load_dotenv()

client_id = os.getenv("ideasoft_client_id")
client_secret = os.getenv("ideasoft_client_secret")
redirect_uri = os.getenv("ideasoft_redirect_uri")

# Construct the URL properly without unnecessary newline characters
url = f"https://www.evan.com/panel/auth?client_id={client_id}&response_type=code&state=2b33fdd45jbevd6nam&redirect_uri={redirect_uri}"

# Make the GET request
response = requests.get(url)

# Print the response
print(response.text)
