from pydantic import BaseModel, Field
from typing import Optional, Dict

class UploadResponse(BaseModel):
    job_id: str = Field(..., description="The unique identifier for this processing job")
    upload_url: str = Field(..., description="The secure S3 URL for file upload")
    required_fields: Dict[str, str] = Field(..., description="AWS-specific form data for the upload")
    instructions: str = Field(..., description="Steps for the client to complete upload")

class JobStatusResponse(BaseModel):
    job_id: str
    status: str = Field(..., description="Current state of the job (PENDING, PROCESSING, COMPLETED)")
    created_at: str
    result: Optional[str] = Field(None, description="Summary of the AI analysis, if finished")