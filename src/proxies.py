import json
import random


def get_random_proxy(file_path):
    try:
        with open(file_path, 'r') as file:
            data = json.load(file)

        # Select a random proxy from the list
        random_proxy = random.choice(data)
        ip = random_proxy.get("ip")
        port = random_proxy.get("port")

        if ip and port:
            return ip, port
        else:
            raise ValueError("Missing IP or port in proxy data.")
    except Exception as e:
        print(f"Error: {e}")
        return None