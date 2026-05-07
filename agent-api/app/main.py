import uuid
import logging
from fastapi import FastAPI, HTTPException, status, Depends, Body, Header
from fastapi.middleware.cors import CORSMiddleware

from . import aws_client
from .config import settings
from .schemas import UploadResponse, JobStatusResponse

# Setting up the logging config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# FastAPI app

app = FastAPI(
    title="Secure AI Agents API",
    description="Zero-trust Document Processing Pipeline",
    version="1.0.1",
)

# Explicity define who can call your API

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.allowed_origins.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "x-api-key"],
)


def get_client_id(x_client_id: str = Header(None, alias="x-client-id")) -> str:
    if not x_client_id:
        logger.error("Request reached Fargate without Gateway context.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing secure context from API Gateway",
        )

    return x_client_id


# Routes


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.post(
    "/api/v1/request-upload",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=UploadResponse,
)
def request_upload(
    filename: str = Body(..., embed=True), client_id: str = Depends(get_client_id)
):
    """The client requests an upload slot, we return a pre-signed URL"""
    job_id = str(uuid.uuid4())
    logger.info(f"Generating secure upload slot for client {client_id}, job {job_id}")

    try:
        upload_data = aws_client.generate_presigned_upload(client_id, job_id, filename)
        aws_client.init_job_record(client_id, job_id, upload_data["object_key"])
    except aws_client.UserInputError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except (aws_client.AWSDatabaseError, aws_client.AWSStorageError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not secure an encrypted upload tunnel.",
        )

    return {
        "job_id": job_id,
        "upload_url": upload_data["url"],
        "required_fields": upload_data["fields"],
        "instructions": "Use a POST request with the 'required_fields' as form-data and the PDF in the 'file' field",
    }


@app.get("/api/v1/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, client_id: str = Depends(get_client_id)):
    """Securely check the status of a document processing job"""
    try:
        status_info = aws_client.get_job_status(client_id, job_id)
    except aws_client.AWSDatabaseError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unreachable.",
        )

    if not status_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found or access denied.",
        )

    return status_info
