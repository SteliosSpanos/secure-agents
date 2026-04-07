from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    aws_region: str = Field(default="eu-central-1")
    s3_bucket_name: str = Field(...)
    sqs_queue_url: str = Field(...)

    max_file_size_mb: int = 10
    api_key_header_name: str = "X-api-key"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
