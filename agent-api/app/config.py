from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    # AWS Config
    aws_region: str = Field(default="eu-central-1", alias="AWS_REGION")
    s3_bucket_name: str = Field(..., alias="S3_BUCKET_NAME")
    jobs_table_name: str = Field(..., alias="DYNAMODB_JOBS_TABLE")

    # Security
    # We use '...' to indicate this MUST be provided (e.g. by ECS/Terraform)
    kms_key_arn: str = Field(..., alias="KMS_KEY_ARN")

    # App Settings
    max_file_size_mb: int = Field(default=50, alias="MAX_FILE_SIZE_MB")

    # Use a list for origins to make CORS setup easier
    # Pydantic will automatically turn a comma-separated string from ECS into a list!
    allowed_origins: List[str] = Field(
        default=["http://localhost:3000"], alias="ALLOWED_ORIGINS"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_ignore_empty=True
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Export a global instance for easy import
settings = get_settings()
