import boto3
import time
import logging
import re
from datetime import datetime, timezone
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError
from typing import Optional, Dict
from .config import settings


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


aws_config = Config(
    region_name=settings.AWS_REGION,
    retries={"max_attempts": 3, "mode": "standard"},
    connect_timeout=5,
    read_timeout=15,
)


class AWSDatabaseError(Exception):
    pass


class AWSStorageError(Exception):
    pass


class UserInputError(Exception):
    pass


try:
    session = boto3.Session()
    s3_client = session.client("s3", config=aws_config)
    dynamodb = session.resource("dynamodb", config=aws_config)
    jobs_table = dynamodb.Table(settings.JOBS_TABLE_NAME)
except Exception:
    logger.exception("Failed to initialize AWS Session.")
    raise RuntimeError("AWS Client initialization failed. Check credentials/IAM roles.")


def build_object_key(client_id: str, job_id: str, filename: str) -> str:
    """Validates the filename and returns the canonical S3 object key"""
    safe_name = re.sub(r"[^a-zA-Z0-9.\-_]", "_", filename)

    if not safe_name.lower().endswith("pdf"):
        logger.warning(f"Client {client_id} attempted to upload non-PDF: {filename}")
        raise UserInputError("Only .pdf files are allowed.")

    stem = safe_name.rsplit(".", 1)[0]
    if len(stem) < 1:
        logger.warning(f"Client {client_id} supplied an invalid filename: {filename}")
        raise UserInputError("Invalid filename.")

    return f"{client_id}/uploads/{job_id}/{safe_name}"


def generate_presigned_upload(client_id: str, job_id: str, object_key: str) -> Dict:
    """Generates a secure S3 presigned URL (acts as a ticket)"""
    try:
        response = s3_client.generate_presigned_post(
            Bucket=settings.S3_BUCKET_NAME,
            Key=object_key,
            Fields={
                "x-amz-server-side-encryption": "aws:kms",
                "x-amz-server-side-encryption-aws-kms-key-id": settings.KMS_KEY_ARN,
                "x-amz-meta-client-id": client_id,
                "x-amz-meta-job-id": job_id,
                "Content-Type": "application/pdf",
            },
            Conditions=[
                ["content-length-range", 1, settings.MAX_FILE_SIZE_MB * 1024 * 1024],
                {"x-amz-server-side-encryption": "aws:kms"},
                {"x-amz-server-side-encryption-aws-kms-key-id": settings.KMS_KEY_ARN},
                {"x-amz-meta-client-id": client_id},
                {"x-amz-meta-job-id": job_id},
                ["starts-with", "$Content-Type", "application/pdf"],
            ],
            ExpiresIn=1800,
        )

        return {
            "url": response["url"],
            "fields": response["fields"],
            "object_key": object_key,
        }
    except (ClientError, BotoCoreError) as e:
        logger.exception("Failed to sign S3 request.")
        raise AWSStorageError("Failed to generate secure upload tunnel.") from e
    except Exception as e:
        logger.exception("Unexpected error during presigned URL generation.")
        raise RuntimeError(
            "An unexpected error occurred while generating the upload URL."
        ) from e


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
            "result": item.get("result_summary"),
        }
    except (ClientError, BotoCoreError) as e:
        logger.exception("Failed to fetch job status.")
        raise AWSDatabaseError("Database unreachable.") from e
    except Exception as e:
        logger.exception("Unexpected error during job status retrieval.")
        raise RuntimeError(
            "An unexpected error occurred while retrieving job status."
        ) from e


def init_job_record(client_id: str, job_id: str, s3_path: str) -> None:
    """Logs the job as PENDING to ensure auditability before upload starts"""

    expiration = int(time.time()) + (24 * 60 * 60)

    try:
        jobs_table.put_item(
            Item={
                "client_id": client_id,
                "job_id": job_id,
                "status": "PENDING_UPLOAD",
                "s3_path": s3_path,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": expiration,
            },
            ConditionExpression="attribute_not_exists(client_id) AND attribute_not_exists(job_id)",
        )
    except ClientError as e:
        # A record with this job_id already exists, which should never happen since we use UUIDs.
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.exception(
                f"Job record for client {client_id}, job {job_id} already exists."
            )
            raise AWSDatabaseError("Job ID collision detected.") from e
        logger.exception("Failed to initialize job record in DynamoDB.")
        raise AWSDatabaseError("Failed to initialize job record.") from e
    except BotoCoreError as e:
        logger.exception("Job record initialization failed due to AWS service error.")
        raise AWSDatabaseError(
            "AWS service error during job record initialization."
        ) from e
    except Exception as e:
        logger.exception("Unexpected error during job record initialization.")
        raise RuntimeError(
            "An unexpected error occurred while initializing the job record."
        ) from e
