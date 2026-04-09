import boto3
import logging
import re
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

# Custom Exceptions so FastAPI knows exactly what failed

class AWSDatabaseError(Exception): pass
class AWSStorageError(Exception): pass
class UserInputError(Exception): pass

try:
    session = boto3.Session()
    s3_client = session.client("s3", config=aws_config)
    sqs_client = session.client("sqs", config=aws_config)
    dynamodb_client = session.client("dynamodb", config=aws_config)
except Exception as e:
    logger.exception("Failed to initialize AWS Session.")
    raise RuntimeError("AWS Client initialization failed. Check credentials/IAM roles.")

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
    except (ClientError, BotoCoreError) as e:
        logger.exception("DynamoDB lookup failed.")
        raise AWSDatabaseError("Database unreachable.") from e



def generate_presigned_upload(client_id: str, job_id: str, filename: str) -> Dict:
    """Generates a secure S3 presigned URL (acts as a ticket)"""
    safe_name = re.sub(r'[^a-zA-Z0-9.\-_]', '_', filename)
    if not safe_name.lower().endswith(".pdf"):
        logger.warning("Client {client_id} attempted to upload non-PDF: {filename}")
        raise UserInputError("Only .pdf files are allowed.")

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
        logger.exception("Failed to sign S3 request.")
        raise AWSStorageError("Failed to generate secure upload tunnel.") from e 



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
            logger.warning("Unauthorized status check: Client {client_id} tried to access job {job_id}")
            return None

        return {
            "job_id": job_id,
            "status": item.get("status", {}).get("S"),
            "created_at": item.get("created_at", {}).get("S"),
            "result": item.get("result_summary", {}).get("S")
        }
    except (ClientError, BotoCoreError) as e:
        logger.exception("Failed to fetch job status.")
        raise AWSDatabaseError("Database unreachable.") from e



def init_job_record(client_id: str, job_id: str, s3_path: str) -> None:
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
    except (ClientError, BotoCoreError) as e:
        logger.exception("Job logging failed.")
        raise AWSDatabaseError("Failed to initialize job record.") from e