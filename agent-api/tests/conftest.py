import os
import sys

# Make sure `app` is importable regardless of the directory pytest is invoked from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("DYNAMODB_JOBS_TABLE", "test-jobs-table")
os.environ.setdefault(
    "KMS_KEY_ARN", "arn:aws:kms:eu-central-1:123456789012:key/test-key"
)
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-central-1")
