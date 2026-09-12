import base64
import json
import time
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from app import aws_client
from app.config import settings

CLIENT_ID = "client-1"
JOB_ID = "job-1"


@pytest.mark.parametrize(
    "filename,expected_suffix",
    [
        ("report.pdf", "report.pdf"),
        ("Report.PDF", "Report.pdf"),
        ("my report (1).PDF", "my_report__1_.pdf"),
    ],
)
def test_build_object_key_accepts_and_normalizes(filename, expected_suffix):
    key = aws_client.build_object_key(CLIENT_ID, JOB_ID, filename)

    assert key == f"{CLIENT_ID}/uploads/{JOB_ID}/{expected_suffix}"
    assert key.endswith(".pdf")
    assert not key.endswith(".PDF")


@pytest.mark.parametrize(
    "filename",
    [
        "reportpdf",
        "report.txt",
        ".pdf",
    ],
)
def test_build_object_key_rejects_invalid_filenames(filename):
    with pytest.raises(aws_client.UserInputError):
        aws_client.build_object_key(CLIENT_ID, JOB_ID, filename)


def test_get_job_status_calls_dynamodb_with_str_job_id():
    """DynamoDB's Key mapping must receive a plain str, never a UUID object."""
    fake_item = {
        "status": "PROCESSING",
        "created_at": "2024-01-01T00:00:00+00:00",
        "result_summary": None,
    }
    job_id = "11111111-1111-1111-1111-111111111111"

    with patch.object(aws_client, "jobs_table") as mock_table:
        mock_table.get_item.return_value = {"Item": fake_item}
        result = aws_client.get_job_status("client-1", job_id)

    _, kwargs = mock_table.get_item.call_args
    assert isinstance(kwargs["Key"]["job_id"], str)
    assert kwargs["Key"] == {"client_id": "client-1", "job_id": job_id}
    assert result["status"] == "PROCESSING"


def test_get_job_status_returns_none_when_missing():
    with patch.object(aws_client, "jobs_table") as mock_table:
        mock_table.get_item.return_value = {}
        result = aws_client.get_job_status("client-1", "does-not-exist")

    assert result is None


def test_init_job_record_sets_ttl_to_initial_days_from_now():
    before = int(time.time())

    with patch.object(aws_client, "jobs_table") as mock_table:
        aws_client.init_job_record(CLIENT_ID, JOB_ID, "s3://bucket/key.pdf")

    after = int(time.time())
    _, kwargs = mock_table.put_item.call_args
    expected_ttl_seconds = settings.JOB_INITIAL_TTL_DAYS * 24 * 60 * 60

    expires_at = kwargs["Item"]["expires_at"]
    assert before + expected_ttl_seconds <= expires_at <= after + expected_ttl_seconds


# --- generate_presigned_upload ---


def test_generate_presigned_upload_policy_conditions():
    """This is a pure local SigV4 signing operation - no network call - so we
    exercise the real function and inspect the base64-encoded policy it
    produces."""
    object_key = f"{CLIENT_ID}/uploads/{JOB_ID}/report.pdf"

    result = aws_client.generate_presigned_upload(CLIENT_ID, JOB_ID, object_key)

    assert result["object_key"] == object_key
    assert "url" in result
    assert "fields" in result

    policy_b64 = result["fields"]["policy"]
    policy = json.loads(base64.b64decode(policy_b64))
    conditions = policy["conditions"]

    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    assert ["content-length-range", 1, max_bytes] in conditions
    assert {"x-amz-server-side-encryption": "aws:kms"} in conditions
    assert {
        "x-amz-server-side-encryption-aws-kms-key-id": settings.KMS_KEY_ARN
    } in conditions
    assert ["starts-with", "$Content-Type", "application/pdf"] in conditions


def test_generate_presigned_upload_raises_aws_storage_error_on_client_error():
    with patch.object(aws_client, "s3_client") as mock_s3:
        mock_s3.generate_presigned_post.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}},
            "GeneratePresignedPost",
        )

        with pytest.raises(aws_client.AWSStorageError):
            aws_client.generate_presigned_upload(
                CLIENT_ID, JOB_ID, f"{CLIENT_ID}/uploads/{JOB_ID}/report.pdf"
            )
