import uuid 
import logging
import os
from fastapi import FastAPI, UploadFile, File, HTTPException, status, Depends, Security
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware

from . import aws_client
from .config import settings

# Setting up the logging config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# FastAPI app

app = FastAPI(
    title="Secure AI Agents API",
    description="Zero-trust Document Processing Pipeline",
    version="1.0.1"
)


api_key_header = APIKeyHeader(name=settings.api_key_header_name, auto_error=False)

async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """Zero-trust, verify the client's identity before any processing"""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="API key missing from header"
        )
    
    client_id = aws_client.verify_api_key_in_dynamodb(api_key)
    
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Invalid or inactive API key"
        )
    return client_id


# Explicity define who can call your API

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # SECURITY: Restrict this to your specific domain in production
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"]
)


# Routes

@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.post("/api/v1/process-pdf", status_code=status.HTTP_202_ACCEPTED)
def process_pdf(
    file: UploadFile = File(...),
    client_id: str = Depends(verify_api_key)
):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Only PDFs accepted")

    header_bytes = file.file.read(4) # Magic number verification
    file.file.seek(0)

    if header_bytes != b"%PDF":
        logger.warning(f"Malicious file attempt from {client_id}. Magic bytes: {header_bytes}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid PDF structure detected")

    max_bytes = settings.max_file_size_mb * 1024 * 1024
    if file.size > max_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large")

    job_id = str(uuid.uuid4())
    safe_name = os.path.basename(file.filename).replace(" ", "_")
    s3_key = f"{client_id}/uploads/{job_id}/{safe_name}"

    if not aws_client.upload_pdf_to_s3(file.file, s3_key):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Secure storage failed")

    message_id = aws_client.send_job_to_sqs(job_id, s3_key, client_id)

    if not message_id:
        aws_client.delete_pdf_object(s3_key)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Job queueing failed. S3 cleanup triggered")

    return {
        "job_id": job_id,
        "status": "accepted",
        "vault_path": s3_key,
        "sqs_message_id": message_id
    }
