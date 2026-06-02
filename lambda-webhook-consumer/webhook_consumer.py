import os
import json
import logging
import urllib.request
import hmac
import hashlib
import boto3
from botocore.exceptions import ClientError, BotoCoreError
from botocore.config import Config

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


aws_config = Config(
    retries={"max_attempts": 3, "mode": "standard"},
    connect_timeout=2,
    read_timeout=10,
)


dynamodb = boto3.resource("dynamodb", config=aws_config)

API_KEYS_TABLE_NAME = os.environ.get("API_KEYS_TABLE")
JOBS_TABLE_NAME = os.environ.get("JOBS_TABLE")
if not API_KEYS_TABLE_NAME or not JOBS_TABLE_NAME:
    raise RuntimeError("Critical environment variables are missing.")

api_keys_table = dynamodb.Table(API_KEYS_TABLE_NAME)
jobs_table = dynamodb.Table(JOBS_TABLE_NAME)


# Whethe Lambda finishes or crashes AWS deletes and changes the visibilty of messages automaticallyn
def lambda_handler(event, context):
    """
    Processes SQS messages containing job completion info.
    Fetches client webhook URL and job summary, then sends a POST request.
    """
    batch_item_failures = []

    for record in event.get("Records", []):
        message_id = record.get("messageId")
        try:
            # Parse SQS message
            message_body = json.loads(record.get("body", "{}"))
            client_id = message_body.get("client_id")
            job_id = message_body.get("job_id")

            if not client_id or not job_id:
                logger.error(
                    "Malformed message: Missing client_id or job_id. MessageID: %s",
                    message_id,
                )
                continue

            webhook_config = get_webhook_config(api_keys_table, client_id)
            if not webhook_config:
                logger.warning(
                    "No active webhook configuration found for client %s. Skipping notification.",
                    client_id,
                )
                continue

            webhook_url = webhook_config.get("webhook_url")
            webhook_secret = webhook_config.get("webhook_secret")

            if not webhook_url or not webhook_secret:
                logger.warning(
                    "Missing webhook_url or webhook_secret for client %s. Skipping notification.",
                    client_id,
                )
                continue

            summary = get_job_summary(jobs_table, client_id, job_id)
            if summary is None:
                logger.warning(
                    "Job %s not found for client %s. Skipping notification.",
                    job_id,
                    client_id,
                )
                continue

            send_webhook_notification(
                webhook_url, webhook_secret, client_id, job_id, summary
            )

            logger.info(
                "Successfully notified client %s for job %s.", client_id, job_id
            )

        except Exception:
            logger.exception("Unexpected error processing SQS record: %s.", message_id)
            batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}


def get_webhook_config(table, client_id):
    """Retrieves the webhook_url for a specific client_id using get_item"""
    try:
        response = table.get_item(Key={"client_id": client_id})
        item = response.get("Item")

        if item and item.get("active", True):
            return {
                "webhook_url": item.get("webhook_url"),
                "webhook_secret": item.get("webhook_secret"),
            }

        return None
    except (ClientError, BotoCoreError):
        logger.exception(
            "Database error while fetching webhook URL for client %s.", client_id
        )
        return None
    except Exception:
        logger.exception(
            "Unexpected error while fetching webhook URL for client %s.", client_id
        )
        return None


def get_job_summary(table, client_id, job_id):
    """Retrieves the result_summary for a specific job"""
    try:
        response = table.get_item(Key={"client_id": client_id, "job_id": job_id})
        item = response.get("Item")

        if item:
            return item.get("result_summary", "No summary available")

        return None
    except (ClientError, BotoCoreError):
        logger.exception("Database error while fetching summary for job %s.", job_id)
        return None
    except Exception:
        logger.exception("Unexpected error while fetching summary for job %s.", job_id)
        return None


def send_webhook_notification(url, secret_key, client_id, job_id, summary):
    """Sends a POST request to the client's webhook URL"""
    payload = {
        "event": "JOB_COMPLETED",
        "client_id": client_id,
        "job_id": job_id,
        "status": "COMPLETED",
        "summary": summary,
    }

    data = json.dumps(payload).encode("utf-8")

    signature = hmac.new(secret_key.encode("utf-8"), data, hashlib.sha256).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-SecureAgents-Signature": signature,
        "X-Webhook-Delivery-ID": f"evt_{job_id}",
    }

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.getcode()
            if status >= 200 and status < 300:
                return True
            else:
                logger.error(
                    "Webhook delivery failed with status %d for client %s.",
                    status,
                    client_id,
                )
                raise Exception(f"Webhook returned status {status}")
    except Exception:
        logger.exception("Failed to send webhook to %s.", url)
        raise
