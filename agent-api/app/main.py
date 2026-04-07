import uuid 
import logging
from fastapi import FastAPI, UploadFile, File, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware

from . import aws_client
from .config import settings


MAX_FILE_SIZE_MB = 10 
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Setting up the logging config

# console_handler = logging.StreamHandler()
# file_handler = logging.FileHandler("app_errors.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    # handlers=[console_handler, file_handler]
)
logger = logging.getLogger(__name__)


# FastAPI app

app = FastAPI(
    title="Secure AI Agents API",
    description="Zero-trust Document Processing Pipeline",
    version="1.0.0"
)


# Explicity define who can call your API

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Change to ["https://your-dashboard.com"] in prod
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"]
)


# Mock Auth

async def get_current_client_id() -> str:
    return "demo_law_firm_01"


# Routes

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "version": app.version}


@app.post("/process-pdf", status_code=status.HTTP_202_ACCEPTED, tags=["Processing"])
def process_pdf(
    file: UploadFile=File(...),
    client_id: str=Depends(get_current_client_id)
):
    logger.info(f"Received file upload request from client '{client_id}': {file.filename}.")

    if file.content_type != "application/pdf":
        logger.warning(f"Rejected invalid file type: {file.content_type}.")
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Only PDF files are supported"
        )

    if file.size > MAX_FILE_SIZE_BYTES:
        logger.warning(f"Rejected oversized file: {file.size} bytes.")
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the max allowed size of {MAX_FILE_SIZE_MB} MB"
        )

    job_id = str(uuid.uuid4())
    s3_key = f"tenant_{client_id}/uploads/{job_id}_{file.filename}"

    upload_success = aws_client.upload_pdf_to_s3(file.file, s3_key)
    if not upload_success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Storage layer error. Failed to dispatch job to AI"
        )

    message_id = aws_client.send_job_to_sqs(job_id, s3_key, client_id)
    if not message_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Queue layer error. Failed to dispatch job to AI"
        )

    logger.info(f"Successfully dispatched job '{job_id}' for '{client_id}'")
    return {
        "status": "queued",
        "message": "Document securely vaulted and queued for AI analysis",
        "job_id": job_id,
        "sqs_message_id": message_id
    }


@app.get("/status/{job_id}", tags=["Processing"])
async def get_status(job_id: str, client_id: str = Depends(get_current_client_id)):
    return {
        "job_id": job_id,
        "client_id": client_id,
        "status": "processing",
        "message": "The AI is currently reviewing the document"
    }
