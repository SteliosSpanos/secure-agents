from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    aws_region: str = Field(default="eu-central-1")
    s3_bucket_name: str = Field(...)

    jobs_table_name: str = Field(
        default="agents_Jobs",
        validation_alias="DYNAMODB_JOBS_TABLE"
    )

    max_file_size_mb: int = 50
    allowed_origins: str = Field(default="http://localhost:3000")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
