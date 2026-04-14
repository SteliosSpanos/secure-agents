import secrets
import hashlib

def generate_client_key(client_name: str):
    raw_key = "ak_live_" + secrets.token_urlsafe(32)

    hashed_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    print("=== SAVING TO DYNAMODB ===")
    print(f"Client ID: {client_name}")
    print(f"Stored Hash: {hashed_key}\n")

    print("=== SEND TO CLIENT ===")
    print(f"Raw API key: {raw_key}")
    