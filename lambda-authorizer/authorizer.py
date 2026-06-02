# Lambda function that is attached to the API Gateway and handles authorization.
# Every lambda has the (event, context) signature:
# 1. event -> dictionary that contains data sent by the service that triggered it
# (It's different depending on the trigger)
# 2. context -> object that contains metadata about the physical execution


import os
import hashlib
import boto3
import logging
from botocore.exceptions import ClientError, BotoCoreError
from botocore.config import Config
from boto3.dynamodb.conditions import Key


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

aws_config = Config(
    retries={"max_attempts": 3, "mode": "standard"},
    connect_timeout=2,
    read_timeout=10,  # Don't hang API Gateway waiting for a slow DB
)


# Handling Database and TCP connections outside of the handler for reduced latency of cold starts
dynamodb = boto3.resource("dynamodb", config=aws_config)

TABLE_NAME = os.environ.get("API_KEYS_TABLE")  # From terraform
EXPECTED_ORIGIN_SECRET = os.environ.get("ORIGIN_SECRET")
if not TABLE_NAME or not EXPECTED_ORIGIN_SECRET:
    raise RuntimeError("Critical environment variables are missing.")

api_keys_table = dynamodb.Table(TABLE_NAME)


def lambda_handler(event, context):
    """Verifies the API key before the request hits the ALB"""
    headers = event.get("headers", {})
    origin_header = headers.get("x-origin-verify")

    if origin_header != EXPECTED_ORIGIN_SECRET:
        logger.critical(
            "SECURITY ALERT: Request bypassed CloudFront/WAF. Missing or invalid X-Origin-Verify header."
        )
        return {"isAuthorized": False}

    api_key = headers.get("x-api-key")

    if not api_key:
        logger.warning("Request missing x-api-key header.")
        return {"isAuthorized": False}

    hashed_key = hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    try:
        response = api_keys_table.query(
            IndexName="ApiKeyIndex",
            KeyConditionExpression=Key("api_key").eq(hashed_key),
            Limit=1,
        )
        items = response.get("Items", [])

        if not items:
            logger.warning("Access denied: Key hash %s...", hashed_key[:8])
            return {"isAuthorized": False}

        item = items[0]
        is_active = item.get("active", False)

        if is_active:
            client_id = item.get("client_id", "unknown_client")
            logger.info("Authorized client: %s.", client_id)

            return {"isAuthorized": True, "context": {"client_id": client_id}}

        logger.warning("Invalid or inactive API key: %s...", hashed_key[:8])
        return {"isAuthorized": False}
    except (ClientError, BotoCoreError):
        logger.exception("AWS Infrastructure error occurred during authorization.")
        return {"isAuthorized": False}
    except Exception:
        logger.exception("Unexpected internal Python error.")
        return {"isAuthorized": False}
