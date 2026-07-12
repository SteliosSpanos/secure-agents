# Because client_id is the hash_key in the DynamoDB table,
# everytime we run with the same client_id it overwrites the previous record

import secrets
import hashlib
import boto3
import logging
import sys
import argparse
import time
import os
from botocore.exceptions import ClientError, BotoCoreError
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)

region = os.environ.get("AWS_REGION", "eu-central-1")
table_name = os.environ.get("API_KEYS_TABLE", "agents_APIKeys")
webhook_url = os.environ.get("WEBHOOK_URL")

session = boto3.Session(region_name=region)
dynamodb = session.resource("dynamodb")
api_keys_table = dynamodb.Table(table_name)


def generate_client_key(client_name: str, webhook_url: str = None) -> dict:
    """Generates a secure API key, hashes it and saves it to DynamoDB"""
    raw_key = "ak_live_" + secrets.token_urlsafe(32)
    hashed_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    item = {"api_key": hashed_key, "client_id": client_name, "active": True}

    raw_webhook_secret = None
    if webhook_url:
        item["webhook_url"] = webhook_url
        raw_webhook_secret = "whsec_" + secrets.token_urlsafe(32)
        item["webhook_secret"] = (
            raw_webhook_secret  # Stored in plain text for Lambda to read
        )

    try:
        api_keys_table.put_item(Item=item)

        return {
            "client_id": client_name,
            "raw_key": raw_key,
            "webhook_url": webhook_url,
            "webhook_secret": raw_webhook_secret,
        }
    except (ClientError, BotoCoreError) as e:
        logger.exception("AWS Infrastructure Error.")
        raise RuntimeError("AWS database operation failed.") from e


def deactivate_key(raw_api_key) -> tuple[bool, str]:
    """Safely revokes an API key and schedules it for deletion in 90 days"""
    hashed_key = hashlib.sha256(raw_api_key.encode("utf-8")).hexdigest()
    expiration = int(time.time()) + (90 * 24 * 60 * 60)

    try:
        response = api_keys_table.query(
            IndexName="ApiKeyIndex",
            KeyConditionExpression=Key("api_key").eq(hashed_key),
            Limit=1,
        )

        items = response.get("Items", [])
        if not items:
            logger.warning("Deactivation targeted an API key that doesn't exist.")
            return False, ""

        client_id = items[0]["client_id"]

        api_keys_table.update_item(
            Key={"client_id": client_id},
            UpdateExpression="SET active = :val, expires_at = :ttl",
            ExpressionAttributeValues={":val": False, ":ttl": expiration},
            ConditionExpression="attribute_exists(client_id)",
        )

        return True, client_id
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.exception(
                "Race condition: Client ID was removed during deactivation."
            )
            return False, ""
        logger.exception("AWS API Error during key deactivation.")
        raise RuntimeError("AWS transaction update failed.") from e
    except BotoCoreError:
        logger.exception("BotoCore SDK Error.")
        raise RuntimeError("AWS transmission path dropped.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="SecureAgents API Key Manager")

    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument(
        "--generate", action="store_true", help="Generate a new API key"
    )
    action_group.add_argument(
        "--deactivate", action="store_true", help="Deactivate an existing key"
    )

    parser.add_argument(
        "--client-id", type=str, help="Client ID (required for --generate)"
    )
    parser.add_argument(
        "--key", type=str, help="Raw API key string (required for --deactivate)"
    )
    parser.add_argument(
        "--webhook-url", type=str, help="Optional webhook URL for new key"
    )

    args = parser.parse_args()

    try:
        if args.generate:
            if not args.client_id:
                parser.error("--client-id is required when using --generate")

            creds = generate_client_key(args.client_id, args.webhook_url)

            print("\n--- API Key Generated and Saved ---")
            print(f"Client ID: {creds['client_id']}")
            print(f"Raw API Key: {creds['raw_key']}")
            if creds["webhook_url"]:
                print(f"Webhook URL: {creds['webhook_url']}")
                print(f"Webhook Secret: {creds['webhook_secret']}")
            print("----------------------------------\n")
            sys.exit(0)

        elif args.deactivate:
            if not args.key:
                parser.error("--key is required when using --deactivate")

            success, client_id = deactivate_key(args.key)
            if success:
                print(f"SUCCESS: Deactivated API key for client: {client_id}")
                sys.exit(0)
            else:
                print(
                    "ERROR: API key not found or deactivation failed.", file=sys.stderr
                )
                sys.exit(1)
    except Exception as e:
        logger.exception(
            "A fatal top-level runtime failure dropped processing threads."
        )
        print(f"\nCRITICAL: {e}\n", file=sys.stderr)
        sys.exit(1)
