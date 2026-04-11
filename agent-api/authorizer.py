import os
import hashlib
import boto3
import logging


logger = logging.getLogger()
logger.setLevel(logging.INFO)


dynamodb = boto3.resource("dynamodb")
table_name = os.environ.get("API_KEYS_TABLE", "agents_APIKeys")
table = dynamodb.Table(table_name)



def lambda_handler(event, context):
    """Verifies the API key before the request hits the ALB"""
    headers = event.get("headers", {})
    api_key = headers.get("x-api-key")

    if not api_key:
        logger.warning("Request missing x-api-key header.")
        return {"isAuthorized": False}

    hashed_key = hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    try:
        response = table.get_item(Key={"api_key": hashed_key})
        item = response.get("Item")

        if item and item.get("active", True):
            client_id = item.get("client_id")
            logger.info(f"Authorized client: {client_id}.")

            return {
                "isAuthorized": True,
                "context": {
                    "client_id": client_id
                }
            }

        logger.warning(f"Invalid or inactive API key: {hashed_key[:8]}...")
        return {"isAuthorized": False}
    except Exception as e:
        logger.exception("Authorizer database error.")
        return {"isAuthorized": False}
