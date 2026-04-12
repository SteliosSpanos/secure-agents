from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    aws_region: str = Field(
        default="eu-central-1",
        validation_alias="AWS_REGION"
    )
    sqs_queue_url: str = Field(
        default="",
        validation_alias="SQS_QUEUE_URL"
    )
    bedrock_model_id: str = Field(
        default="meta.llama3-8b-instruct-v1:0",
        validation_alias="BEDROCK_MODEL_ID"
    )

    jobs_table_name: str = Field(
        default="agents_Jobs",
        validation_alias="DYNAMODB_JOBS_TABLE"
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()