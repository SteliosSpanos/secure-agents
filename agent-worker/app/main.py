import os
import sys
import tempfile
import time
import json
import boto3
import logging
import signal
from urllib.parse import unquote_plus
from botocore.exceptions import ClientError, BotoCoreError
from botocore.config import Config
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .config import settings


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("worker_daemon")


aws_config = Config(
    region_name=settings.AWS_REGION,
    retries={"max_attempts": 3, "mode": "standard"},
    connect_timeout=5,  # If we cant establish a TCP connection in 5 sec, throw an error
    read_timeout=300,  # The amount of time the SDK will wait for a response before timing out
    # Must be > SQS WaitTimeSeconds and accommodate Bedrock
)

try:
    session = boto3.Session()
    sqs = session.client("sqs", config=aws_config)
    s3 = session.client("s3", config=aws_config)
    bedrock = session.client("bedrock-runtime", config=aws_config)
    dynamodb = session.resource("dynamodb", config=aws_config)
    jobs_table = dynamodb.Table(settings.JOBS_TABLE_NAME)
except Exception:
    logger.exception("Failed to initialize AWS session.")
    sys.exit(1)


shutdown_flag = False
active_job = {"client_id": None, "job_id": None, "receipt_handle": None}


class PDFExtractionTimeoutError(Exception):
    pass


def _raise_extraction_timeout(signum, frame):
    raise PDFExtractionTimeoutError("PDF parsing exceeded the time limit")


def write_heartbeat() -> None:
    """Drops a liveness timestamp for the ECS container health check to read"""
    try:
        with open(settings.HEARTBEAT_FILE_PATH, "w") as heartbeat_file:
            heartbeat_file.write(str(time.time()))
    except OSError:
        logger.exception("Failed to write heartbeat file.")


def handle_sigterm(*args):
    global shutdown_flag
    logger.info("SIGTERM received. Fargate container scaling in.")
    shutdown_flag = True

    # If we are in the middle of a Bedrock call, rescue the database Records
    if active_job["job_id"]:
        logger.info(
            f"Emergency Rescue: Reverting job {active_job['job_id']} to PENDING_UPLOAD."
        )
        try:
            # Only revert if the job is still PROCESSING
            reverted = update_job(
                active_job["client_id"],
                active_job["job_id"],
                "PENDING_UPLOAD",
                expected_status="PROCESSING",
            )

            if reverted:
                # Make the SQS message visible immediately so another worker can pick it up
                sqs.change_message_visibility(
                    QueueUrl=settings.SQS_QUEUE_URL,
                    ReceiptHandle=active_job["receipt_handle"],
                    VisibilityTimeout=0,
                )
                logger.info("Rescue complete. Exiting gracefully.")
            else:
                logger.info(
                    f"Job {active_job['job_id']} already left PROCESSING, leaving the SQS message alone."
                )
        except (ClientError, BotoCoreError):
            logger.exception(f"AWS SDK error during rescue of {active_job['job_id']}.")
        except Exception:
            logger.exception("Failed to rescue job during SIGTERM.")
        finally:
            sys.exit(0)


signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)


def extend_sqs_visibility(
    receipt_handle: str, timeout: int = settings.VISIBILITY_TIMEOUT_SECONDS
):
    """Extends the SQS visibility timeout to prevent other workers from taking this job"""
    try:
        sqs.change_message_visibility(
            QueueUrl=settings.SQS_QUEUE_URL,
            ReceiptHandle=receipt_handle,
            VisibilityTimeout=timeout,
        )
        logger.info(f"Extended visibility by {timeout}s.")
    except (ClientError, BotoCoreError):
        logger.warning("Job may become visible to other workers if processing is slow.")
    except Exception:
        logger.exception("Unexpected heartbeat failure.")


def extract_text_from_s3_pdf(bucket: str, key: str) -> str:
    """Downloads PDF from S3 into a temporary file and extracts text to prevent OOM errors"""
    decoded_key = unquote_plus(key)

    try:
        head = s3.head_object(Bucket=bucket, Key=decoded_key)
        content_length = head.get("ContentLength", 0)

        max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        if content_length > max_bytes:
            raise ValueError("PDF exceeds maximum allowed size")
    except (ClientError, BotoCoreError):
        logger.exception(f"Couldn't HEAD object s3://{bucket}/{decoded_key}.")
        raise

    logger.info(f"Downloading s3://{bucket}/{decoded_key}")

    tmp_file_path = None
    previous_alarm_handler = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            s3.download_fileobj(bucket, decoded_key, tmp_file)
            tmp_file_path = tmp_file.name

        # Hard wall-clock timeout covering PdfReader construction through the page
        # loop, so a pathological/malicious PDF can't hang the worker indefinitely.
        previous_alarm_handler = signal.signal(
            signal.SIGALRM, _raise_extraction_timeout
        )
        signal.alarm(settings.PDF_EXTRACTION_TIMEOUT_SECONDS)

        reader = PdfReader(tmp_file_path)

        if reader.is_encrypted:
            logger.warning(f"File {decoded_key} is encrypted.")
            raise ValueError("PDF is password protected or encrypted.")

        num_pages = len(reader.pages)
        if num_pages == 0:
            raise ValueError("PDF is empty or contains no readable pages.")

        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"

            if len(text) > (settings.CHAR_LIMIT * 1.2):
                logger.warning(
                    f"Extracted text limit reached for {decoded_key}. Truncating."
                )
                break

        return text.strip()
    except PdfReadError:
        logger.exception(f"PdfReadError for {decoded_key}.")
        raise ValueError("PDF structure is corrupted")
    except PDFExtractionTimeoutError:
        logger.exception(f"PDF parsing timed out for {decoded_key}.")
        raise ValueError("PDF parsing exceeded the time limit")
    except (ClientError, BotoCoreError):
        logger.exception(f"Failed to download or process s3://{bucket}/{decoded_key}")
        raise
    except Exception:
        logger.exception(f"Unexpected parsing error for {decoded_key}.")
        raise ValueError("Could not parse PDF")
    finally:
        signal.alarm(0)
        if previous_alarm_handler is not None:
            signal.signal(signal.SIGALRM, previous_alarm_handler)
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)


def process_document(
    client_id: str, job_id: str, bucket: str, key: str, receipt_handle: str
) -> tuple[str, bool]:
    """Extracts text and asks Bedrock to summarize it"""
    extend_job_lock(client_id, job_id)
    extend_sqs_visibility(receipt_handle)

    document_text = extract_text_from_s3_pdf(bucket, key)
    write_heartbeat()

    if not document_text:
        raise ValueError("PDF contained no readable text.")

    char_limit = settings.CHAR_LIMIT
    is_truncated = len(document_text) > char_limit
    if is_truncated:
        logger.warning(
            f"Document {key} exceeds limit. Truncating to {char_limit} chars."
        )
        document_text = document_text[:char_limit]

    extend_job_lock(client_id, job_id)
    extend_sqs_visibility(receipt_handle)

    logger.info("Text extracted. Invoking Agent...")

    system_prompt = [
        {
            "text": (
                "You are an expert legal administrative assistant. "
                "Your task is to provide objective, high-density summaries of legal documents. "
                "Rules:\n"
                "- Only provide a 3-sentence summary.\n"
                "- Do not include personal opinions or introductory phrases like 'Here is the summary'.\n"
                "- If the document is not legal or professional text, state 'Invalid document type'.\n"
                "- Maintain a professional and neutral tone."
            )
        }
    ]

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "text": f"Please summarize the following document content:\n\n{document_text}"
                }
            ],
        }
    ]

    response = bedrock.converse(
        modelId=settings.BEDROCK_MODEL_ID,
        system=system_prompt,
        messages=messages,
        inferenceConfig={"maxTokens": 512, "temperature": 0.3, "topP": 0.9},
    )
    write_heartbeat()

    try:
        summary = response["output"]["message"]["content"][0]["text"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as e:
        raise RuntimeError(f"Unexpected Bedrock converse response shape: {e}") from e
    return summary, is_truncated


def update_job(
    client_id: str,
    job_id: str,
    status_val: str,
    result_summary: str | None = None,
    expected_status: str | None = None,
) -> bool:
    """Updates the DynamoDB table with status and optional summary."""

    new_expiration = int(time.time()) + (30 * 24 * 60 * 60)

    update_expr = "SET #s = :s, expires_at = :ttl"
    expr_names = {"#s": "status"}
    expr_values = {":s": status_val.upper(), ":ttl": new_expiration}

    if result_summary:
        update_expr += ", result_summary = :r"
        expr_values[":r"] = result_summary

    kwargs = {
        "Key": {"client_id": client_id, "job_id": job_id},
        "UpdateExpression": update_expr,
        "ExpressionAttributeNames": expr_names,
        "ExpressionAttributeValues": expr_values,
    }

    if expected_status:
        kwargs["ConditionExpression"] = "#s = :expected_status"
        kwargs["ExpressionAttributeValues"][":expected_status"] = expected_status

    try:
        jobs_table.update_item(**kwargs)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False  # Another worker already claimed the job
        raise
    except BotoCoreError:
        logger.exception(f"AWS SDK Transport Error for job {job_id}.")
        raise
    except Exception:
        logger.exception(
            f"Unexpected system error during DynamoDB update for job {job_id}."
        )
        raise


class JobRecordMissingError(Exception):
    pass


class LockLostError(Exception):
    pass


def acquire_job_lock(client_id: str, job_id: str) -> bool:
    """Claims a job for processing using a lock-lease, tolerating a crashed
    worker's stale lock instead of a naive PENDING_UPLOAD-only equality check"""
    now = int(time.time())
    lease_expiration = now + settings.VISIBILITY_TIMEOUT_SECONDS
    new_expiration = int(time.time()) + (30 * 24 * 60 * 60)

    kwargs = {
        "Key": {"client_id": client_id, "job_id": job_id},
        "UpdateExpression": "SET #s = :processing, lock_expires_at = :lease, expires_at = :ttl",
        "ConditionExpression": (
            "#s = :pending OR (#s = :processing AND "
            "(attribute_not_exists(lock_expires_at) OR lock_expires_at < :now))"
        ),
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": {
            ":processing": "PROCESSING",
            ":pending": "PENDING_UPLOAD",
            ":lease": lease_expiration,
            ":ttl": new_expiration,
            ":now": now,
        },
        # Asks DynamoDB to return the pre-update item on a failed condition check, so we can tell "record missing" apart from "record exists but condition didn't match"
        "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
    }

    try:
        jobs_table.update_item(**kwargs)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            if e.response.get("Item") is None:
                raise JobRecordMissingError(
                    f"No job record for client {client_id}, job {job_id}."
                ) from e
            return False  # Another worker already holds a live lease
        raise
    except BotoCoreError:
        logger.exception(f"AWS SDK Transport Error acquiring lock for job {job_id}.")
        raise
    except Exception:
        logger.exception(f"Unexpected system error acquiring lock for job {job_id}.")
        raise


def extend_job_lock(client_id: str, job_id: str) -> None:
    """Pushes the lock lease forward. Must succeed before the SQS visibility
    timeout is extended and if the lock lease can't be confirmed as extended,
    the caller can no longer be sure it exclusively holds the job and must
    stop processing"""
    new_lease = int(time.time()) + settings.VISIBILITY_TIMEOUT_SECONDS

    try:
        jobs_table.update_item(
            Key={"client_id": client_id, "job_id": job_id},
            UpdateExpression="SET lock_expires_at = :lease",
            ConditionExpression="#s = :processing",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":lease": new_lease,
                ":processing": "PROCESSING",
            },
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.warning(
                f"Could not extend lock lease for job {job_id}; no longer PROCESSING."
            )
            raise LockLostError(
                f"Lock lease for job {job_id} is no longer held."
            ) from e
        logger.exception(f"Failed to extend lock lease for job {job_id}.")
        raise LockLostError(f"Failed to extend lock lease for job {job_id}.") from e
    except BotoCoreError as e:
        logger.exception(f"AWS SDK error extending lock lease for job {job_id}.")
        raise LockLostError(f"Failed to extend lock lease for job {job_id}.") from e
    except Exception as e:
        logger.exception(f"Unexpected error extending lock lease for job {job_id}.")
        raise LockLostError(f"Failed to extend lock lease for job {job_id}.") from e


def main():
    # Per-job error handling:
    # - AWS ClientError/BotoCoreError -> revert to PENDING_UPLOAD and re-raise. Message stays in the queue for retry
    # - ValueError (bad/unusable document) -> terminal FAILED with a rejection reason, then the SQS message is deleted (retrying can't help)
    # - Any other exception -> no job-row write, re-raise, message is left for SQS redrive and lands in the DLQ
    logger.info("Worker daemon started. Listening for SQS messages...")

    while not shutdown_flag:
        write_heartbeat()
        try:
            response = sqs.receive_message(
                QueueUrl=settings.SQS_QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
            )

            messages = response.get("Messages", [])
            if not messages:
                continue

            for msg in messages:
                receipt_handle = msg["ReceiptHandle"]
                try:
                    body = json.loads(msg["Body"])

                    for record in body.get("Records", []):
                        if "s3" not in record:
                            continue

                        bucket = record["s3"]["bucket"]["name"]
                        key = record["s3"]["object"]["key"]

                        decoded_key = unquote_plus(key)
                        parts = decoded_key.split("/")
                        if len(parts) >= 3:
                            client_id = parts[0]
                            job_id = parts[2]
                        else:
                            logger.warning(f"Malformed S3 key: {key}")
                            continue

                        try:
                            lock_acquired = acquire_job_lock(client_id, job_id)
                        except JobRecordMissingError:
                            logger.error(
                                f"Job record missing for {client_id}/{job_id}; "
                                "leaving message for redrive."
                            )
                            raise

                        if not lock_acquired:
                            logger.info(
                                f"Job {job_id} lock denied (already processing/completed)."
                            )
                            continue

                        # Populate active_job for SIGTERM handler
                        active_job["client_id"] = client_id
                        active_job["job_id"] = job_id
                        active_job["receipt_handle"] = receipt_handle

                        try:
                            summary, is_truncated = process_document(
                                client_id, job_id, bucket, key, receipt_handle
                            )

                            final_summary = summary
                            if is_truncated:
                                final_summary = (
                                    f"[Note: document was truncated to {settings.CHAR_LIMIT} characters] "
                                    + summary
                                )

                            completed = update_job(
                                client_id,
                                job_id,
                                "COMPLETED",
                                result_summary=final_summary,
                                expected_status="PROCESSING",
                            )
                            if completed:
                                logger.info(
                                    f"Job {job_id} successfully completed for client {client_id}."
                                )
                            else:
                                logger.warning(
                                    f"Job {job_id} was reclaimed by another worker "
                                    "before COMPLETED could be written; leaving it alone."
                                )
                        except (ClientError, BotoCoreError):
                            logger.exception(f"Retryable AWS error for job {job_id}.")
                            update_job(
                                client_id,
                                job_id,
                                "PENDING_UPLOAD",
                                expected_status="PROCESSING",
                            )
                            raise
                        except ValueError as e:
                            logger.warning(f"Job {job_id} rejected: {e}")
                            failed = update_job(
                                client_id,
                                job_id,
                                "FAILED",
                                result_summary=f"Document rejected: {e}",
                                expected_status="PROCESSING",
                            )
                            if not failed:
                                logger.warning(
                                    f"Job {job_id} was reclaimed by another worker "
                                    "before FAILED could be written; leaving it alone."
                                )
                        except Exception:
                            logger.exception(
                                f"Unhandled error for job {job_id}; leaving message for redrive."
                            )
                            raise
                        finally:
                            active_job.update(
                                {
                                    "client_id": None,
                                    "job_id": None,
                                    "receipt_handle": None,
                                }
                            )

                    sqs.delete_message(
                        QueueUrl=settings.SQS_QUEUE_URL, ReceiptHandle=receipt_handle
                    )
                except (ClientError, BotoCoreError):
                    logger.warning(
                        "AWS error occurred. Message left in queue for retry."
                    )
                except Exception:
                    logger.exception(
                        "Unexpected error processing message body; leaving message for redrive."
                    )
        except (ClientError, BotoCoreError):
            logger.exception("Critical SQS Polling error.")
            time.sleep(10)
        except Exception:
            logger.exception("Unexpected worker crash. Restarting loop...")
            time.sleep(5)

    logger.info("Worker shut down successfully.")


if __name__ == "__main__":
    main()

# Trigger deployment
