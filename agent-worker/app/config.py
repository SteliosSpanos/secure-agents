from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    aws_region: str = Field(default="eu-central-1")
    sqs_queue_url: str = Field(...)

    jobs_table_name: str = Field(default="agents_Jobs", validation_alias="DYNAMODB_JOBS_TABLE")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()