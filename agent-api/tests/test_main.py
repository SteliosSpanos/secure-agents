import uuid
from unittest.mock import patch

from app import aws_client as aws_client_module
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)

HEADERS = {"x-client-id": "test-client"}


def test_get_job_status_passes_str_to_aws_client():
    """The UUID path param must be converted to str before hitting aws_client,
    which in turn passes it straight through as a raw DynamoDB key."""
    job_id = uuid.uuid4()

    with patch("app.main.aws_client.get_job_status") as mock_get_status:
        mock_get_status.return_value = {
            "job_id": str(job_id),
            "status": "COMPLETED",
            "created_at": "2024-01-01T00:00:00+00:00",
            "result": "done",
        }
        response = client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS)

    assert response.status_code == 200
    called_args = mock_get_status.call_args.args
    assert called_args[0] == "test-client"
    assert isinstance(called_args[1], str)
    assert called_args[1] == str(job_id)


def test_get_job_status_200():
    job_id = uuid.uuid4()
    with patch("app.main.aws_client.get_job_status") as mock_get_status:
        mock_get_status.return_value = {
            "job_id": str(job_id),
            "status": "PENDING_UPLOAD",
            "created_at": "2024-01-01T00:00:00+00:00",
            "result": None,
        }
        response = client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == str(job_id)
    assert body["status"] == "PENDING_UPLOAD"


def test_get_job_status_404_when_not_found():
    job_id = uuid.uuid4()
    with patch("app.main.aws_client.get_job_status", return_value=None):
        response = client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS)

    assert response.status_code == 404


def test_get_job_status_422_on_invalid_uuid():
    response = client.get("/api/v1/jobs/not-a-uuid", headers=HEADERS)

    assert response.status_code == 422


def test_get_job_status_503_on_database_error():
    job_id = uuid.uuid4()
    with patch(
        "app.main.aws_client.get_job_status",
        side_effect=aws_client_module.AWSDatabaseError(),
    ):
        response = client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS)

    assert response.status_code == 503


# --- POST /api/v1/request-upload ---


def test_request_upload_202_happy_path():
    with (
        patch(
            "app.main.aws_client.build_object_key",
            return_value="test-client/uploads/job-1/report.pdf",
        ),
        patch("app.main.aws_client.init_job_record"),
        patch(
            "app.main.aws_client.generate_presigned_upload",
            return_value={
                "url": "https://bucket.s3.amazonaws.com/",
                "fields": {"key": "test-client/uploads/job-1/report.pdf"},
                "object_key": "test-client/uploads/job-1/report.pdf",
            },
        ),
    ):
        response = client.post(
            "/api/v1/request-upload",
            json={"filename": "report.pdf"},
            headers=HEADERS,
        )

    assert response.status_code == 202
    body = response.json()
    assert body["upload_url"] == "https://bucket.s3.amazonaws.com/"
    assert body["required_fields"] == {"key": "test-client/uploads/job-1/report.pdf"}
    assert "job_id" in body


def test_request_upload_400_on_build_object_key_user_input_error():
    with patch(
        "app.main.aws_client.build_object_key",
        side_effect=aws_client_module.UserInputError("Only .pdf files are allowed."),
    ):
        response = client.post(
            "/api/v1/request-upload",
            json={"filename": "report.txt"},
            headers=HEADERS,
        )

    assert response.status_code == 400


def test_request_upload_500_on_init_job_record_database_error():
    with (
        patch(
            "app.main.aws_client.build_object_key",
            return_value="test-client/uploads/job-1/report.pdf",
        ),
        patch(
            "app.main.aws_client.init_job_record",
            side_effect=aws_client_module.AWSDatabaseError(),
        ),
    ):
        response = client.post(
            "/api/v1/request-upload",
            json={"filename": "report.pdf"},
            headers=HEADERS,
        )

    assert response.status_code == 500


def test_request_upload_400_on_generate_presigned_upload_user_input_error():
    with (
        patch(
            "app.main.aws_client.build_object_key",
            return_value="test-client/uploads/job-1/report.pdf",
        ),
        patch("app.main.aws_client.init_job_record"),
        patch(
            "app.main.aws_client.generate_presigned_upload",
            side_effect=aws_client_module.UserInputError("Invalid filename."),
        ),
    ):
        response = client.post(
            "/api/v1/request-upload",
            json={"filename": "report.pdf"},
            headers=HEADERS,
        )

    assert response.status_code == 400


def test_request_upload_500_on_generate_presigned_upload_storage_error():
    with (
        patch(
            "app.main.aws_client.build_object_key",
            return_value="test-client/uploads/job-1/report.pdf",
        ),
        patch("app.main.aws_client.init_job_record"),
        patch(
            "app.main.aws_client.generate_presigned_upload",
            side_effect=aws_client_module.AWSStorageError(),
        ),
    ):
        response = client.post(
            "/api/v1/request-upload",
            json={"filename": "report.pdf"},
            headers=HEADERS,
        )

    assert response.status_code == 500


def test_request_upload_401_missing_client_id_header():
    response = client.post(
        "/api/v1/request-upload",
        json={"filename": "report.pdf"},
    )

    assert response.status_code == 401
