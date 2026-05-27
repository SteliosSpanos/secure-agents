from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    # AWS Config
    aws_region: str = Field(default="eu-central-1", alias="AWS_REGION")
    sqs_queue_url: str = Field(..., alias="SQS_QUEUE_URL")
    jobs_table_name: str = Field(..., alias="DYNAMODB_JOBS_TABLE")

    # AI Model Settings
    bedrock_model_id: str = Field(
        default="anthropic.claude-3-haiku-20240307-v1:0",
        alias="BEDROCK_MODEL_ID",
    )

    # App Settings
    max_file_size_mb: int = Field(default=50, alias="MAX_FILE_SIZE_MB")
    char_limit: int = Field(default=15000, alias="CHAR_LIMIT")

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True
    )


# Useful for testing
@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
