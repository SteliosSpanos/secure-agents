import os
import sys

# Make sure `app` is importable regardless of the directory pytest is invoked from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault(
    "SQS_QUEUE_URL",
    "https://sqs.eu-central-1.amazonaws.com/123456789012/test-queue",
)
os.environ.setdefault("DYNAMODB_JOBS_TABLE", "test-jobs-table")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-central-1")
os.environ.setdefault("AWS_REGION", "eu-central-1")

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def mock_jobs_table():
    """Spins up an in-memory DynamoDB table shaped like terraform/dynamodb.tf's
    Jobs table (client_id HASH, job_id RANGE), so ConditionExpression logic in
    app.main is evaluated by a real DynamoDB engine instead of mocked out."""
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="eu-central-1")
        table = resource.create_table(
            TableName=os.environ["DYNAMODB_JOBS_TABLE"],
            KeySchema=[
                {"AttributeName": "client_id", "KeyType": "HASH"},
                {"AttributeName": "job_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "client_id", "AttributeType": "S"},
                {"AttributeName": "job_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        yield table
