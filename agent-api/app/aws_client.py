import boto3
import json
import logging
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError
from typing import BinaryIO, Optional
from .config import settings

# Setting up logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
if not logger.handlers:
    logger.addHandler(ch)


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
    logger.info("AWS Boto3 Session and Clients initialized successfully.")
except Exception as e:
    logger.critical(f"Failed to initialize AWS Session: {str(e)}.")
    raise RuntimeError("AWS Client initialization failed. Check credentials/IAM roles.")

# Service functions

def upload_pdf_to_s3(file_obj: BinaryIO, object_name: str) -> bool:
    try:
        logger.info(f"Attempting to upload '{object_name}' to S3 bucket '{setting.s3_bucket_name}'.")

        s3_client.upload_fileobj(
            file_obj,
            settings.s3_bucket_name,
            object_name,
            ExtraArgs={
                "ContentType": "application/pdf",
                "ServerSideEncryption": "AES256"
            }
        )

        logger.info(f"Successfully uploaded '{object_name}' to S3.")
        return True
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"S3 ClientError [{error_code}]: {error_msg} - Object: {object_name}.")
        return False
    except BotoCoreError as e:
        logger.error(f"S3 BotoCoreError: {str(e)} - Object: {object_name}.")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error uploading to S3: {str(e)}")
        return False

def send_job_to_sqs(job_id: str, s3_key: str, client_id: str) -> Optional[str]:
    payload = {
        "job_id": job_id, 
        "s3_bucket": settings.s3_bucket_name,
        "s3_key": s3_key,
        "client_id": client_id,
        "action": "summarize_and_extract"
    }

    try:
        logger.info(f"Sending job '{job_id}' to SQS client '{client_id}'.")

        response = sqs_client.send_message(
            QueueUrl=settings.sqs_queue_url,
            MessageBody=json.dumps(payload)
        )

        message_id = response.get("MessageId")
        logger.info(f"Successfully queued job '{job_id}'. SQS MessageId: {message_id}.")
        return message_id
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"SQS ClientError [{error_code}]: {error_msg} - JobID: {job_id}.")
        return None
    except BotoCoreError as e:
        logger.error(f"SQS BotoCoreError: {str(e)} - JobID: {job_id}.")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error sending message to SQS: {str(e)}.")
        return None
        

