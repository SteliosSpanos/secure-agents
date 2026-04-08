import uuid 
import logging
import hashlib
from fastapi import FastAPI, UploadFile, File, HTTPException, status, Depends, Security, Body
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

def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """Zero-trust, verify the client's identity before any processing"""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="API key missing from header"
        )
    
    # Hash the incoming raw key to compare with the stored SHA-256 hash in DynamoDB
    hashed_key = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    client_id = aws_client.verify_api_key_in_dynamodb(hashed_key)
    
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Invalid or inactive API key"
        )
    return client_id


# Explicity define who can call your API

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["POST"],
    allow_headers=["*"]
)


# Routes

@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.post("/api/v1/request-upload", status_code=status.HTTP_202_ACCEPTED)
def request_upload(
    filename: str = Body(..., embed=True),
    client_id: str = Depends(verify_api_key)
):
    """The client requests an upload slot, we return a pre-signed URL"""
    job_id = str(uuid.uuid4())
    logger.info(f"Generating secure upload slot for client {client_id}, job {job_id}")

    upload_data = aws_client.generate_presigned_upload(client_id, job_id, filename)

    if not upload_data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not secure an encrypted upload tunnel"
        )

    if not aws_client.init_job_record(client_id, job_id, upload_data["object_key"]):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pipeline registration failed"
        )

    return {
        "job_id": job_id,
        "upload_url": upload_data["url"],
        "required_fields": upload_data["fields"],
        "instructions": "Use a POST request with the 'required_fields' as form-data and the PDF in the 'file' field"
    }