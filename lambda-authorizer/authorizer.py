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


logger = logging.getLogger()
logger.setLevel(logging.INFO)

aws_config = Config(
    retries={
        "max_attempts": 3,
        "mode": "standard"
    },
    connect_timeout=2,
    read_timeout=10 # Don't hang API Gateway waiting for a slow DB
)


# Handling Database and TCP connections outside of the handler for reduced latecny from cold starts
dynamodb = boto3.resource("dynamodb", config=aws_config)
table_name = os.environ.get("API_KEYS_TABLE", "agents_APIKeys") # From terraform
api_keys_table = dynamodb.Table(table_name)

expected_origin_secret = os.environ.get("ORIGIN_SECRET")


def lambda_handler(event, context):
    """Verifies the API key before the request hits the ALB"""
    headers = event.get("headers", {})

    if not expected_origin_secret:
        logger.error("Configuration error: ORIGIN_SECRET env variable is missing.")
        return {"isAuthorized": False}

    origin_header = headers.get("x-origin-verify")

    if origin_header != expected_origin_secret:
        logger.critical("SECURITY ALERT: Request bypassed CloudFront/WAF. Missing or invalid X-Origin-Verify header.")
        return {"isAuthorized": False}


    api_key = headers.get("x-api-key")

    if not api_key:
        logger.warning("Request missing x-api-key header.")
        return {"isAuthorized": False}

    hashed_key = hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    try:
        response = api_keys_table.get_item(
            Key={"api_key": hashed_key},
            ConsistentRead=True
        )
        item = response.get("Item")

        if not item:
            logger.warning(f"Access denied: Key hash {hashed_key[:8]}...")
            return {"isAuthorized": False}

        is_active = item.get("active", False)

        if is_active:
            client_id = item.get("client_id", "unknown_client")
            logger.info(f"Authorized client: {client_id}.")

            return {
                "isAuthorized": True,
                "context": {
                    "client_id": client_id
                }
            }

        logger.warning(f"Invalid or inactive API key: {hashed_key[:8]}...")
        return {"isAuthorized": False}
    except (ClientError, BotoCoreError):
        logger.exception("AWS Infrastructure error occurred during authorization.")
        return {"isAuthorized": False}
    except Exception:
        logger.exception("Unexpected internal Python error.")
        return {"isAuthorized": False}
