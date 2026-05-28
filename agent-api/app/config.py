from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    # AWS Config
    AWS_REGION: str = Field(default="eu-central-1", alias="AWS_REGION")
    S3_BUCKET_NAME: str = Field(..., alias="S3_BUCKET_NAME")
    JOBS_TABLE_NAME: str = Field(..., alias="DYNAMODB_JOBS_TABLE")

    # Security
    KMS_KEY_ARN: str = Field(..., alias="KMS_KEY_ARN")

    # App Settings
    MAX_FILE_SIZE_MB: int = Field(default=50, alias="MAX_FILE_SIZE_MB")

    # Pydantic will automatically turn a comma-separated string from ECS into a list
    ALLOWED_ORIGINS: List[str] = Field(
        default=["http://localhost:3000"], alias="ALLOWED_ORIGINS"
    )

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Export a global instance for easy import
settings = get_settings()
