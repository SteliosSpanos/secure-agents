from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    AWS_REGION: str = Field(default="eu-central-1", alias="AWS_REGION")
    SQS_QUEUE_URL: str = Field(..., alias="SQS_QUEUE_URL")
    JOBS_TABLE_NAME: str = Field(..., alias="DYNAMODB_JOBS_TABLE")

    BEDROCK_MODEL_ID: str = Field(
        default="anthropic.claude-3-haiku-20240307-v1:0",
        alias="BEDROCK_MODEL_ID",
    )

    MAX_FILE_SIZE_MB: int = Field(default=50, alias="MAX_FILE_SIZE_MB")
    CHAR_LIMIT: int = Field(default=15000, alias="CHAR_LIMIT")

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
