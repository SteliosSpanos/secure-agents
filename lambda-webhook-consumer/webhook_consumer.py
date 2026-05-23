import os
import json
import logging
import urllib.request
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

api_keys_table_name = os.environ.get("API_KEYS_TABLE")
jobs_table_name = os.environ.get("JOBS_TABLE")
if not api_keys_table_name or not jobs_table_name:
    raise RuntimeError("Critical environment variables are missing.")

api_keys_table = dynamodb.Table(api_keys_table_name)
jobs_table = dynamodb.Table(jobs_table_name)


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
                logger.error("Malformed message: Missing client_id or job_id. MessageID: %s", message_id)
                continue

            webhook_url = get_webhook_url(api_keys_table, client_id)
            if not webhook_url:
                logger.warning("No webhook URL found for client %s. Skipping notification.", client_id)
                continue

            summary = get_job_summary(jobs_table, client_id, job_id)
            if summary is None:
                logger.warning("Job %s not found for client %s. Skipping notification.", job_id, client_id)
                continue

            send_webhook_notification(webhook_url, client_id, job_id, summary)
            
            logger.info("Successfully notified client %s for job %s.", client_id, job_id)

        except Exception:
            logger.exception("Unexpected error processing SQS record: %s.", messageId)
            batch_item_failures.append({"itemIdentifier": message_id})

    return {
        "batchItemFailures": batch_item_failures
    }


def get_webhook_url(table, client_id):
    """Retrieves the webhook_url for a specific client_id using get_item"""
    try:
        response = table.get_item(Key={"client_id": client_id})
        item = response.get("Item")

        if item and item.get("active", True):
            return item.get("webhook_url")

        return None
    except (ClientError, BotoCoreError):
        logger.exception("Database error while fetching webhook URL for client %s.", client_id)
        return None
    except Exception:
        logger.exception("Unexpected error while fetching webhook URL for client %s.", client_id)
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


def send_webhook_notification(url, client_id, job_id, summary):
    """Sends a POST request to the client's webhook URL"""
    payload = {
        "event": "JOB_COMPLETED",
        "client_id": client_id,
        "job_id": job_id,
        "status": "COMPLETED",
        "summary": summary
    }
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.getcode()
            if status >= 200 and status < 300:
                return True
            else:
                logger.error("Webhook delivery failed with status %d for client %s.", status, client_id)
                raise Exception(f"Webhook returned status {status}")
    except Exception:
        logger.exception("Failed to send webhook to %s.", url)
        raise
