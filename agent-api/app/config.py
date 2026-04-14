from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    aws_region: str = Field(
        default="eu-central-1",
        validation_alias="AWS_REGION"
    )
    
    s3_bucket_name: str = Field(
        default="", 
        validation_alias="S3_BUCKET_NAME"
    )

    jobs_table_name: str = Field(
        default="agents_Jobs",
        validation_alias="DYNAMODB_JOBS_TABLE"
    )

    max_file_size_mb: int = Field(
        default=50,
        validation_alias="MAX_FILE_SIZE_MB"
    )

    allowed_origins: str = Field(
        default="http://localhost:3000",
        validation_alias="ALLOWED_ORIGINS"
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
