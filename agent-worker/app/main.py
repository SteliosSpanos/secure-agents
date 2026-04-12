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
    read_timeout=60 # Must be > SQS WaitTimeSeconds and accommodate Bedrock
)


sqs = boto3.client("sqs", config=aws_config)
s3 = boto3.client("s3", config=aws_config)
bedrock = boto3.client("bedrock-runtime", config=aws_config)
dynamodb = boto3.resource("dynamodb", config=aws_config)

jobs_table = dynamodb.Table(settings.jobs_table_name)


# Graceful shutdown handler

shutdown_flag = False

def handle_sigterm(*args):
    global shutdown_flag
    logger.info("SIGTERM received. Shutting down gracefully after current task...")
    shutdown_flag = True

signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)



# Business Logic

def extract_text_from_s3_pdf(bucket: str, key: str) -> str:
    """Downloads PDF from S3 into memory and extracts text"""
    decoded_key = unquote_plus(key)

    logger.info(f"Downloading s3://{bucket}/{decoded_key}")
    response = s3.get_object(Bucket=bucket, Key=decoded_key)
    pdf_bytes = response["Body"].read()

    pdf_file = io.BytesIO(pdf_bytes)
    reader = PdfReader(pdf_file)

    text = ""
    for page in reader.pages:
        extracted = page.extract_text()
        if extracted:
            text += extracted + "\n"

    return text.strip()



def process_document(bucket: str, key: str) -> str:
    """Extracts text and asks Bedrock to summarize it"""
    document_text = extract_text_from_s3_pdf(bucket, key)

    if not document_text:
        raise ValueError("PDF contained no readable text.")

    document_text = document_text[:15000]

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

    summary = response["output"]["message"]["content"][0]["text"]
    return summary.strip()


def update_job(job_id: str, status_val: str, result_summary: str = None):
    """Updates the DynamoDB table with status and optional summary."""
    if result_summary:
        jobs_table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET #s = :s, result_summary = :r",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": status_val.upper(),
                ":r": result_summary
            }
        )
    else:
        jobs_table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": status_val.upper()}
        )



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

                        # Extract Job ID: client_id/uploads/job_id/filename.pdf 
                        parts = key.split('/')
                        if len(parts) >= 3:
                            job_id = parts[2]
                        else:
                            logger.warning(f"Malformed S3 key: {key}")
                            continue


                        try:
                            update_job(job_id, "PROCESSING")
                            summary = process_document(bucket, key)
                            update_job(job_id, "COMPLETED", result_summary=summary)
                            logger.info(f"Job {job_id} successfully completed.")
                        except (ClientError, BotoCoreError):
                            logger.exception(f"Retryable AWS error for job {job_id}.")
                            raise
                        except Exception as e:
                            logger.exception(f"Fatal error for job {job_id}.")
                            update_job(job_id, "FAILED", result_summary=str(e))

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