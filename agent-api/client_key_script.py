import secrets
import hashlib
import boto3
import logging
import sys
import os
from botocore.exceptions import ClientError, BotoCoreError

logger = logging.getLogger(__name__)

def generate_client_key(client_name: str):
    region = os.environ.get("AWS_REGION", "eu-central-1")

    raw_key = "ak_live_" + secrets.token_urlsafe(32)
    hashed_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    try:
        session = boto3.Session(region_name=region)
        dynamodb = session.resource("dynamodb")
        api_keys_table = dynamodb.Table("agents_APIKeys")

        api_keys_table.put_item(
            Item={
                "api_key": hashed_key,
                "client_id": client_name,
                "active": True
            }
        )

        print("--- API Key Generated and Saved ---")
        print(f"Client ID: {client_name}")
        print(f"Raw API Key: {raw_key}") # Goes only to the client
    except (ClientError, BotoCoreError):
        logger.exception("AWS Infrastructure Error.")
        print("\nFAILED: Could not save key. Check AWS credentials and table name.\n")
        sys.exit(1)
    except Exception:
        logger.exception("Unexpected Error.")
        print("\nFAILED: An unexpected error occurred.\n")
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    client_name = "TestClient"
    if len(sys.argv) > 1:
        # Check for both positional and flag-style arguments
        if sys.argv[1] == "--client-id" and len(sys.argv) > 2:
            client_name = sys.argv[2]
        else:
            client_name = sys.argv[1]
    else:
        print("Usage: python3 client_key_script.py <client_name> (or --client-id <client_name>)")

    generate_client_key(client_name)

    