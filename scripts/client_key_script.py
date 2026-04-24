import secrets
import hashlib
import boto3
import logging
import sys
import argparse
import time
import os
from botocore.exceptions import ClientError, BotoCoreError

logger = logging.getLogger(__name__)

region = os.environ.get("AWS_REGION", "eu-central-1")
table_name = os.environ.get("API_KEYS_TABLE", "agents_APIKeys")

session = boto3.Session(region_name=region)
dynamodb = session.resource("dynamodb")
api_keys_table = dynamodb.Table(table_name)


def generate_client_key(client_name: str):
    """Generates a secure API key, hashes it and saves it to DynamoDB"""
    raw_key = "ak_live_" + secrets.token_urlsafe(32)
    hashed_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    try:
        api_keys_table.put_item(
            Item={"api_key": hashed_key, "client_id": client_name, "active": True}
        )

        print("--- API Key Generated and Saved ---")
        print(f"Client ID: {client_name}")
        print(f"Raw API Key: {raw_key}")  # Goes only to the client
    except (ClientError, BotoCoreError):
        logger.exception("AWS Infrastructure Error.")
        print("\nFAILED: Could not save key. Check AWS credentials and table name.\n")
        sys.exit(1)
    except Exception:
        logger.exception("Unexpected Error.")
        print("\nFAILED: An unexpected error occurred.\n")
        sys.exit(1)


def deactivate_key(raw_api_key):
    """Safely revokes an API key and schedules it for deletion in 90 days"""
    hashed_key = hashlib.sha256(raw_api_key.encode("utf-8")).hexdigest()

    expiration = int(time.time()) + (90 * 24 * 60 * 60)

    try:
        api_keys_table.update_item(
            Key={"api_key": hashed_key},
            UpdateExpression="SET active = :val, expires_at = :ttl",
            ExpressionAttributeValues={":val": False, ":ttl": expiration},
            ConditionExpression="attribute_exists(api_key)",
        )

        print(f"API key {raw_api_key[:12]}... has been deactivated.")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            print("That API key doesn't exist in the database.\n")
        else:
            logger.exception("AWS API Error.")
            print("\nFAILED: AWS rejected the request. Check IAM permissions.\n")
            sys.exit(1)
    except BotoCoreError:
        logger.exception("BotoCore SDK Error.")
        print("\nFAILED: Could not connect to AWS. Check your network and credentials.")
        sys.exit(1)
    except Exception:
        logger.exception("Unexpected internal error.")
        print("\nFAILED: Unexpected application error occurred.\n")
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(description="SecureAgents API Key Manager")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--client-id", type=str, help="Generate a new key for this client name"
    )
    group.add_argument(
        "--deactivate", type=str, help="The raw API key string to deactivate"
    )

    args = parser.parse_args()

    if args.client_id:
        generate_client_key(args.client_id)
    elif args.deactivate:
        deactivate_key(args.deactivate)
