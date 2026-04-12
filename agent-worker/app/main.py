import io
import time
import json
import boto3
import logging
import signal
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
    read_timeout=15
)


sqs = boto3.client("sqs", config=aws_config)
s3 = boto3.client("s3", config=aws_config)
dynamodb = boto3.resource("dynamodb", config=aws_config)
bedrock = boto3.resource("bedrock-runtime", config=aws_config)

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
    logger.info(f"Downloading s3://{bucket}/{key}")
    response = s3.get_object(Bucket=bucket, Key=key)
    pdf_bytes = response["Body"].read()

    pdf_file = io.BytesIO(pdf_bytes)
    reader = PdfReader(pdf_file)

    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"

    return text.strip()



def process_document(bucket: str, key: str) -> str:
    """Extracts text and asks Bedrock to summarize it"""
    document_text = extract_text_from_s3_pdf(bucket, key)

    if not document_text:
        raise ValueError("PDF contained no readable text.")


    document_text = document_text[:15000]

    logger.info("Text extracted. Invoking Bedrock Llama 3...")
    prompt = f"Provide a 3-sentence summary of the following docuent:\n\n{document_text}"

    body = json.dumps({
        "prompt": prompt,
        "max_gen_len": 512,
        "temperature": 0.5,
        "top_p": 0.9
    })

    response = bedrock.invoke_model(
        modelId="meta.llama3-8b-instruct-v1:0",
        body=body
    )

    result = json.loads(response["body"].read())
    return result.get("generation", "No summary generated.").strip()



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
                body = json.loads(msg["Body"])

                for record in body.get("Records", []):
                    if "s3" not in record:
                        continue

                    s3_info = record["s3"]
                    bucket = s3_info["bucket"]["name"]
                    key = s3_info["object"]["key"]


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
                    except Exception as e:
                        logger.exception(f"Job {job_id} failed during processing.")
                        update_job(job_id, "FAILED", result_summary=f"Error: {str(e)}")

                sqs.delete_message(
                    QueueUrl=settings.sqs_queue_url,
                    ReceiptHandle=receipt_handle
                )
        except Exception as e:
            logger.exception("Worker encountered a critical polling error.")
            time.sleep(5)

    logger.info("Worker shut down successfully.")


if __name__ == "__main__":
    main()