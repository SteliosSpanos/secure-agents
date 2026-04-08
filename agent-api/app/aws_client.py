import boto3
import json
import logging
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError
from typing import BinaryIO, Optional
from .config import settings

# Setting up logging for module

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


# Initialize AWS clients
# Locally it uses ~/.aws/credentials

aws_config = Config(
    region_name=settings.aws_region,
    retries={
        "max_attempts": 3,
        "mode": "standard"
    },
    connect_timeout=5,
    read_timeout=15
)

try:
    session = boto3.Session()
    s3_client = session.client("s3", config=aws_config)
    sqs_client = session.client("sqs", config=aws_config)
except Exception as e:
    logger.critical(f"Failed to initialize AWS Session: {str(e)}.")
    raise RuntimeError("AWS Client initialization failed. Check credentials/IAM roles.")

# Service functions

def upload_pdf_to_s3(file_obj: BinaryIO, object_name: str) -> bool:
    """Uploads a file to S3 with mandatory AES256 encryption at rest"""
    try:
        logger.info(f"Attempting to upload '{object_name}' to S3 bucket '{settings.s3_bucket_name}'.")

        s3_client.upload_fileobj(
            file_obj,
            settings.s3_bucket_name,
            object_name,
            ExtraArgs={
                "ContentType": "application/pdf",
                "ServerSideEncryption": "AES256"
            }
        )
        return True
    except (ClientError, BotoCoreError) as e:
        logger.error(f"S3 Upload failed for {object_name}: {str(e)}")
        return False



def delete_pdf_object(object_name: str):
    """Cleanup function to remove files if the pipeline fails"""
    try:
        s3_client.delete_object(Bucket=settings.s3_bucket_name, Key=object_name)
        logger.info(f"Successfully cleaned up S3 object {object_name}")
    except Exception as e:
        logger.error(f"Failed to cleanup S3 object {object_name}: {str(e)}")



def send_job_to_sqs(job_id: str, s3_key: str, client_id: str) -> Optional[str]:
    """Queues a job with a structured JSON payload"""
    payload = {
        "job_id": job_id, 
        "s3_bucket": settings.s3_bucket_name,
        "s3_key": s3_key,
        "client_id": client_id,
        "action": "summarize_and_extract"
    }

    try:
        response = sqs_client.send_message(
            QueueUrl=settings.sqs_queue_url,
            MessageBody=json.dumps(payload)
        )

        return response.get("MessageId")
    except (ClientError, BotoCoreError) as e:
        logger.error(f"SQS queueing failed for {job_id}: {str(e)}")
        return None
        