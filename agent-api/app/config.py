from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    AWS_REGION: str = Field(default="eu-central-1", alias="AWS_REGION")
    S3_BUCKET_NAME: str = Field(..., alias="S3_BUCKET_NAME")
    JOBS_TABLE_NAME: str = Field(..., alias="DYNAMODB_JOBS_TABLE")

    KMS_KEY_ARN: str = Field(..., alias="KMS_KEY_ARN")

    MAX_FILE_SIZE_MB: int = Field(default=50, alias="MAX_FILE_SIZE_MB")

    ALLOWED_ORIGINS: list[str] = Field(
        default=["http://localhost:3000", "https://d90xnc0ve8xm0.cloudfront.net"],
        alias="ALLOWED_ORIGINS",
    )

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
