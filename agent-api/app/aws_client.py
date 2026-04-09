import boto3
import logging
import os
from datetime import datetime, timezone
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError
from typing import Optional, Dict
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
    dynamodb_client = session.client("dynamodb", config=aws_config)
except Exception as e:
    logger.exception("Failed to initialize AWS Session.")
    raise RuntimeError(f"AWS Client initialization failed. Check credentials/IAM roles: {str(e)}")

# Service functions

def verify_api_key_in_dynamodb(api_key: str) -> Optional[str]:
    """Look up the client ID associated with an API key in DynamoDB"""
    try:
        response = dynamodb_client.get_item(
            TableName=settings.api_keys_table_name,
            Key={"api_key": {"S": api_key}},
            ProjectionExpression="client_id, active"
        )
        
        item = response.get("Item")
        if not item:
            logger.warning(f"Unauthorized access attempt with invalid API key.")
            return None
        
        if not item.get("active", {}).get("BOOL", True):
            logger.warning(f"Access denied: Inactive API key used.")
            return None
            
        return item.get("client_id", {}).get("S")    
    except (ClientError, BotoCoreError):
        logger.exception("DynamoDB lookup failed.")
        return None



def generate_presigned_upload(client_id: str, job_id: str, filename: str) -> Optional[Dict]:
    """Generates a secure S3 presigned URL (acts as a ticket)"""
    safe_name = os.path.basename(filename).replace(" ", "_")
    if not safe_name.lower().endswith(".pdf"):
        logger.warning(f"Client {client_id} attempted to upload non-PDF: {filename}")
        return None

    object_key = f"{client_id}/uploads/{job_id}/{safe_name}"

    try:
        response = s3_client.generate_presigned_post(
            Bucket=settings.s3_bucket_name,
            Key=object_key,
            Fields={
                "x-amz-server-side-encryption": "aws:kms",
                "x-amz-meta-client-id": client_id,
                "x-amz-meta-job-id": job_id,
                "Content-Type": "application/pdf"
            },
            Conditions=[
                ["content-length-range", 1, settings.max_file_size_mb * 1024 * 1024],
                {"x-amz-server-side-encryption": "aws:kms"},
                {"x-amz-meta-client-id": client_id},
                {"x-amz-meta-job-id": job_id},
                ["starts-with", "$Content-Type", "application/pdf"]
            ],
            ExpiresIn=300
        )

        return {
            "url": response["url"],
            "fields": response["fields"],
            "object_key": object_key
        }
    except (ClientError, BotoCoreError) as e:
        logger.exception(f"Failed to sign S3 request: {str(e)}")
        return None



def get_job_status(client_id: str, job_id: str) -> Optional[Dict]:
    """Retrieves the status of a specific job, ensuring the client owns it"""
    try:
        response = dynamodb_client.get_item(
            TableName=settings.jobs_table_name,
            Key={"job_id": {"S": job_id}},
            ProjectionExpression="client_id, #s, s3_path, created_at, result_summary",
            ExpressionAttributeNames={"#s": "status"}
        )

        item = response.get("Item")
        if not item:
            return None

        if item.get("client_id", {}).get("S") != client_id:
            logger.warning(f"Unauthorized status check: Client {client_id} tried to access job {job_id}")
            return None

        return {
            "job_id": job_id,
            "status": item.get("status", {}).get("S"),
            "created_at": item.get("created_at", {}).get("S"),
            "result": item.get("result_summary", {}).get("S")
        }
    except (ClientError, BotoCoreError) as e:
        logger.exception(f"Failed to fetch job status: {str(e)}")
        return None
        return None



def init_job_record(client_id: str, job_id: str, s3_path: str):
    """Logs the job as PENDING to ensure auditability before upload starts"""
    try:
        dynamodb_client.put_item(
            TableName=settings.jobs_table_name,
            Item={
                "job_id": {"S": job_id},
                "client_id": {"S": client_id},
                "status": {"S": "PENDING_UPLOAD"},
                "s3_path": {"S": s3_path},
                "created_at": {"S": datetime.now(timezone.utc).isoformat()}
            }
        )
        return True
    except (ClientError, BotoCoreError):
        logger.exception("Job logging failed.")
        return False