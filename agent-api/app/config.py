from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    aws_region: str = Field(default="eu-central-1")
    s3_bucket_name: str = Field(...)
    sqs_queue_url: str = Field(...)

    jobs_table_name: str = Field(default="agents_Jobs")
    api_keys_table_name: str = Field(default="agents_APIKeys")

    max_file_size_mb: int = 50
    api_key_header_name: str = "X-api-key"
    allowed_origins: str = Field(default="http://localhost:3000")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
