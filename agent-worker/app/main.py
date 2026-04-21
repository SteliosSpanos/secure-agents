import os
import sys
import tempfile
import io
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
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("worker_daemon")


aws_config = Config(
    region_name=settings.aws_region,
    retries={
        "max_attempts": 3,
        "mode": "standard"
    },
    connect_timeout=5,
    read_timeout=300 # Must be > SQS WaitTimeSeconds and accommodate Bedrock
)


sqs = boto3.client("sqs", config=aws_config)
s3 = boto3.client("s3", config=aws_config)
bedrock = boto3.client("bedrock-runtime", config=aws_config)
dynamodb = boto3.resource("dynamodb", config=aws_config)

jobs_table = dynamodb.Table(settings.jobs_table_name)



# SIGTERM handler is called by ECS before it terminates the Fargate task during scaling, deployment...

shutdown_flag = False
active_job = {"client_id": None, "job_id": None, "receipt_handle": None}

def handle_sigterm(*args):
    global shutdown_flag
    logger.info("SIGTERM received. Fargate container scaling in.")
    shutdown_flag = True

    # If we are in the middle of a Bedrock call, rescue the database Records
    if active_job["job_id"]:
        logger.info(f"Emergency Rescue: Reverting job {active_job['job_id']} to PENDING_UPLOAD.")
        try:
            update_job(
                active_job["client_id"],
                active_job["job_id"],
                "PENDING_UPLOAD"
            )

            sqs.change_message_visibility(
                QueueUrl=settings.sqs_queue_url,
                ReceiptHandle=active_job["receipt_handle"],
                VisibilityTimeout=0
            )
            logger.info("Rescue complete. Exiting gracefully.")
        except (ClientError, BotoCoreError):
            logger.exception(f"AWS SDK error during rescue of {active_job['job_id']}.")
        except Exception:
            logger.exception("Failed to rescue job during SIGTERM.")
        finally:
            sys.exit(0)


signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)



def extend_sqs_visibility(receipt_handle: str, timeout: int = 600):
    """Extends the SQS visibility timeout to prevent other workers from taking this job"""
    try:
        sqs.change_message_visibility(
            QueueUrl=settings.sqs_queue_url,
            ReceiptHandle=receipt_handle,
            VisibilityTimeout=timeout
        )
        logger.info(f"Extended visibility by {timeout}s.")
    except (ClientError, BotoCoreError):
        logger.warning("Job may become visible to other workers if processing is slow.")
    except Exception:
        logger.exception("Unexpected heartbeat failure.")


def extract_text_from_s3_pdf(bucket: str, key: str) -> str:
    """Downloads PDF from S3 into a temporary file and extracts text to prevent OOM errors"""
    decoded_key = unquote_plus(key)

    # Check object size before committing to a download 
    try:
        head = s3.head_object(Bucket=bucket, Key=decoded_key)
        content_length = head.get("ContentLength", 0)

        max_bytes = settings.max_file_size_mb * 1024 * 1024
        if content_length > max_bytes:
            raise ValueError("PDF exceeds maximum allowed size")
    except(ClientError, BotoCoreError):
        logger.exception(f"Couldn't HEAD object s3://{bucket}/{decoded_key}.")
        raise

    logger.info(f"Downloading s3://{bucket}/{decoded_key}")
    
    # Use a temporary file to avoid holding the entire PDF in memory
    tmp_file_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            s3.download_fileobj(bucket, decoded_key, tmp_file)
            tmp_file_path = tmp_file.name

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

            if len(text) > (settings.char_limit * 1.2):
                logger.warning(f"Extracted text limit reached for {decoded_key}. Truncating.")
                break

        return text.strip()
    except PdfReadError:
        logger.exception(f"PdfReadError for {decoded_key}.")
        raise ValueError("PDF structure is corrupted")
    except (ClientError, BotoCoreError):
        logger.exception(f"Failed to download or process s3://{bucket}/{decoded_key}")
        raise
    except Exception:
        logger.exception(f"Unexpected parsing error for {decoded_key}.")
        raise ValueError("Could not parse PDF")
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)




def process_document(bucket: str, key: str, receipt_handle: str) -> tuple[str, bool]:
    """Extracts text and asks Bedrock to summarize it"""
    extend_sqs_visibility(receipt_handle)

    document_text = extract_text_from_s3_pdf(bucket, key)

    if not document_text:
        raise ValueError("PDF contained no readable text.")

    is_truncated = len(document_text) > settings.char_limit
    if is_truncated:
        logger.warning(f"Document {key} exceeds limit. Truncating to {settings.char_limit} chars.")
        document_text = document_text[:settings.char_limit]

    extend_sqs_visibility(receipt_handle)

    logger.info("Text extracted. Invoking Bedrock Llama 3...")

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
            ]
        }
    ]

    response = bedrock.converse(
        modelId=settings.bedrock_model_id,
        system=system_prompt,
        messages=messages,
        inferenceConfig={
            "maxTokens": 512,
            "temperature": 0.3,
            "topP": 0.9
        }
    )

    summary = response["output"]["message"]["content"][0]["text"].strip()
    return summary, is_truncated


def update_job(client_id: str, job_id: str, status_val: str, result_summary: str | None = None, expected_status: str | None = None) -> bool:
    """Updates the DynamoDB table with status and optional summary."""

    new_expiration = int(time.time()) + (30 * 24 * 60 * 60)

    update_expr = "SET #s = :s, expires_at = :ttl"
    expr_names = {"#s": "status"}
    expr_values = {
        ":s": status_val.upper(),
        ":ttl": new_expiration
    }

    if result_summary:
        update_expr += ", result_summary = :r"
        expr_values[":r"] = result_summary

    kwargs = {
        "Key": {"client_id": client_id, "job_id": job_id},
        "UpdateExpression": update_expr,
        "ExpressionAttributeNames": expr_names,
        "ExpressionAttributeValues": expr_values
    }

    if expected_status:
        kwargs["ConditionExpression"] = "#s = :expected_status"
        kwargs["ExpressionAttributeValues"][":expected_status"] = expected_status

    try:
        jobs_table.update_item(**kwargs)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
    except BotoCoreError:
        logger.exception(f"AWS SDK Transport Error for job {job_id}.")
        raise
    except Exception:
        logger.exception(f"Unexpected system error during DynamoDB update for job {job_id}.")
        raise


def main():
    logger.info("Worker daemon started. Listening for SQS messages...")

    while not shutdown_flag:
        try:
            response = sqs.receive_message(
                QueueUrl=settings.sqs_queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20
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

                        # Extract Client ID and Job ID: {client_id}/uploads/{job_id}/{filename}.pdf 
                        decoded_key = unquote_plus(key)
                        parts = decoded_key.split('/')
                        if len(parts) >= 3:
                            client_id = parts[0]
                            job_id = parts[2]
                        else:
                            logger.warning(f"Malformed S3 key: {key}")
                            continue

                        lock_acquired = update_job(
                            client_id,
                            job_id,
                            status_val="PROCESSING",
                            expected_status="PENDING_UPLOAD"
                        )

                        if not lock_acquired:
                            logger.info(f"Job {job_id} lock denied (already processing/completed).")
                            continue

                        # Populate active_job for SIGTERM handler 
                        active_job["client_id"] = client_id
                        active_job["job_id"] = job_id
                        active_job["receipt_handle"] = receipt_handle


                        try:
                            summary, is_truncated = process_document(bucket, key, receipt_handle)

                            final_summary = summary
                            if is_truncated:
                                final_summary = f"[Note: document was truncated to {settings.char_limit} characters]" + summary

                            update_job(client_id, job_id, "COMPLETED", result_summary=final_summary)
                            logger.info(f"Job {job_id} successfully completed for client {client_id}.")
                        except (ClientError, BotoCoreError):
                            logger.exception(f"Retryable AWS error for job {job_id}.")
                            update_job(client_id, job_id, "PENDING_UPLOAD")
                            raise
                        except Exception:
                            logger.exception(f"Fatal error for job {job_id}.")
                            update_job(client_id, job_id, "FAILED", result_summary="Document processing failed")
                        finally:
                            active_job.update({"client_id": None, "job_id": None, "receipt_handle": None})

                    sqs.delete_message(
                        QueueUrl=settings.sqs_queue_url,
                        ReceiptHandle=receipt_handle
                    )
                except (ClientError, BotoCoreError):
                    logger.warning("AWS error occurred. Message left in queue for retry.")
                except Exception:
                    logger.exception("Unexpected error processing message body.")
                    sqs.delete_message(
                        QueueUrl=settings.sqs_queue_url,
                        ReceiptHandle=receipt_handle
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