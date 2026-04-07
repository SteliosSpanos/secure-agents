from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    aws_region: str = os.getenv("AWS_REGION", "eu-central-1")
    s3_bucket_name: str = os.getenv("S3_BUCKET_NAME")
    sqs_queue_url: str = os.getenv("SQS_QUEUE_URL")

    class Config:
        env_file = ".env"


settings = Settings()
