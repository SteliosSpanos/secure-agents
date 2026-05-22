import os
import json
import logging
import boto3
from botocore.exceptions import ClientError, BotoCoreError
from botocore.config import Config


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


aws_config = Config(
    retries={"max_attempts": 3, "mode": "standard"},
    connect_timeout=2,
    read_timeout=10
)

sqs = boto3.client("sqs", config=aws_config)
WEBHOOK_QUEUE_URL = os.environ.get("WEBHOOK_QUEUE_URL")

def lambda_handler(event, context):
    """Triggers from DynamoDB stream when a new job is completed and sends the a message to SQS for the webhook service"""
    if not WEBHOOK_QUEUE_URL:
        logger.error("Configuration error: WEBHOOK_QUEUE_URL environment variable is not set.")
        return {"success": False}
    
    records_processed = 0
    for record in event.get("Records", []):
        try:
            # We only care about record updates (MODIFY)
            if record.get("eventName") != "MODIFY":
                continue

            dynamodb_data = record.get("dynamodb", {})
            new_image = dynamodb_data.get("NewImage", {})
            old_image = dynamodb_data.get("OldImage", {})

            new_status = new_image.get("status", {}).get("S")
            old_status = old_image.get("status", {}).get("S")

            if new_status == "COMPLETED" and old_status != "COMPLETED":
                client_id = new_image.get("client_id", {}).get("S")
                job_id = new_image.get("job_id", {}).get("S")

                if not client_id or not job_id:
                    logger.error("Malformed record: missing client_id or job_id (eventID = %s)", record.get("eventID"))
                    continue

                logger.info("Job %s for client %s is COMPLETED. Triggering webhook.", job_id, client_id)

                message_body = {
                    "event": "job_completed",
                    "client_id": client_id,
                    "job_id": job_id,
                    "timestamp": int(dynamodb_data.get("ApproximateCreationDateTime", 0))
                }

                sqs.send_message(
                    QueueUrl=WEBHOOK_QUEUE_URL,
                    MessageBody=json.dumps(message_body),
                    MessageAttributes={
                        "MessageType": {
                            "DataType": "String",
                            "StringValue": "JobCompletionNotification"
                        }
                    }
                )

                records_processed += 1
        except (ClientError, BotoCoreError):
            logger.exception("AWS SDK error while processing record: %s", record.get("eventID"))
        except Exception:
            logger.exception("Unexpected error while processing record: %s", record.get("eventID"))

    logger.info("Successfully processed %d job completion events.", records_processed)
    return {"success": True, "processed_count": records_processed}