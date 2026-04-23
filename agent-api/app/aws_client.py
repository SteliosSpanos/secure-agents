import boto3
import time
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

class AWSDatabaseError(Exception):
    pass
class AWSStorageError(Exception):
    pass
class UserInputError(Exception):
    pass


# Initializing a session

try:
    session = boto3.Session()
    s3_client = session.client("s3", config=aws_config)
    dynamodb = session.resource("dynamodb", config=aws_config)
    jobs_table = dynamodb.Table(settings.jobs_table_name)
except Exception:
    logger.exception("Failed to initialize AWS Session.")
    raise RuntimeError("AWS Client initialization failed. Check credentials/IAM roles.")


# Service functions

def generate_presigned_upload(client_id: str, job_id: str, filename: str) -> Dict:
    """Generates a secure S3 presigned URL (acts as a ticket)"""
    safe_name = re.sub(r'[^a-zA-Z0-9.\-_]', '_', filename)
    if not safe_name.lower().endswith(".pdf"):
        logger.warning(f"Client {client_id} attempted to upload non-PDF: {filename}")
        raise UserInputError("Only .pdf files are allowed.")

    object_key = f"{client_id}/uploads/{job_id}/{safe_name}"

    try:
        response = s3_client.generate_presigned_post(
            Bucket=settings.s3_bucket_name,
            Key=object_key,
            Fields={
                "x-amz-server-side-encryption": "aws:kms",
                "x-amz-server-side-encryption-aws-kms-key-id": settings.kms_key_arn,
                "x-amz-meta-client-id": client_id,
                "x-amz-meta-job-id": job_id,
                "Content-Type": "application/pdf"
            },
            Conditions=[
                ["content-length-range", 1, settings.max_file_size_mb * 1024 * 1024],
                {"x-amz-server-side-encryption": "aws:kms"},
                {"x-amz-server-side-encryption-aws-kms-key-id": settings.kms_key_arn},
                {"x-amz-meta-client-id": client_id},
                {"x-amz-meta-job-id": job_id},
                ["starts-with", "$Content-Type", "application/pdf"]
            ],
            ExpiresIn=1800
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
        response = jobs_table.get_item(Key={"client_id": client_id, "job_id": job_id})
        item = response.get("Item")

        if not item:
            return None

        return {
            "job_id": job_id,
            "status": item.get("status"),
            "created_at": item.get("created_at"),
            "result": item.get("result_summary")
        }
    except (ClientError, BotoCoreError) as e:
        logger.exception("Failed to fetch job status.")
        raise AWSDatabaseError("Database unreachable.") from e



def init_job_record(client_id: str, job_id: str, s3_path: str) -> None:
    """Logs the job as PENDING to ensure auditability before upload starts"""

    # The TTL is set to 24 hours from now if it's garbage
    expiration = int(time.time()) + (24 * 60 * 60)

    try:
       jobs_table.put_item(
        Item={
            "client_id": client_id,
            "job_id": job_id,
            "status": "PENDING_UPLOAD",
            "s3_path": s3_path,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expiration
        },
        ConditionExpression="attribute_not_exists(client_id) AND attribute_not_exists(job_id)"
       )
    except (ClientError, BotoCoreError) as e:
        logger.exception("Job logging failed.")
        raise AWSDatabaseError("Failed to initialize job record.") from e