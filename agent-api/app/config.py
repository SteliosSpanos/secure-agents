from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    AWS_REGION: str = Field(default="eu-central-1", alias="AWS_REGION")
    S3_BUCKET_NAME: str = Field(..., alias="S3_BUCKET_NAME")
    JOBS_TABLE_NAME: str = Field(..., alias="DYNAMODB_JOBS_TABLE")

    KMS_KEY_ARN: str = Field(..., alias="KMS_KEY_ARN")

    MAX_FILE_SIZE_MB: int = Field(default=50, alias="MAX_FILE_SIZE_MB")

    # The TTL for a job record must comfortably outlive sqs_retention_days
    JOB_INITIAL_TTL_DAYS: int = Field(default=7, alias="JOB_INITIAL_TTL_DAYS")

    ALLOWED_ORIGINS: list[str] = Field(
        default=[],
        alias="ALLOWED_ORIGINS",
    )

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
