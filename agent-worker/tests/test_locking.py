import time
from unittest.mock import patch

import pytest
from app import main as worker

# --- Unit-level: verify the exact shape of the DynamoDB calls we build ---


def test_acquire_job_lock_builds_expected_condition_and_values():
    with patch.object(worker, "jobs_table") as mock_table:
        result = worker.acquire_job_lock("client-1", "job-1")

    assert result is True
    _, kwargs = mock_table.update_item.call_args
    assert kwargs["Key"] == {"client_id": "client-1", "job_id": "job-1"}
    assert kwargs["ConditionExpression"] == (
        "#s = :pending OR (#s = :processing AND "
        "(attribute_not_exists(lock_expires_at) OR lock_expires_at < :now))"
    )
    assert "attribute_not_exists(#s)" not in kwargs["ConditionExpression"]
    assert kwargs["ExpressionAttributeNames"] == {"#s": "status"}

    values = kwargs["ExpressionAttributeValues"]
    assert values[":processing"] == "PROCESSING"
    assert values[":pending"] == "PENDING_UPLOAD"
    assert isinstance(values[":lease"], int)
    assert isinstance(values[":now"], int)
    assert (
        values[":lease"] - values[":now"] == worker.settings.VISIBILITY_TIMEOUT_SECONDS
    )


def test_extend_job_lock_builds_expected_condition():
    with patch.object(worker, "jobs_table") as mock_table:
        worker.extend_job_lock("client-1", "job-1")

    _, kwargs = mock_table.update_item.call_args
    assert kwargs["Key"] == {"client_id": "client-1", "job_id": "job-1"}
    assert kwargs["UpdateExpression"] == "SET lock_expires_at = :lease"
    assert kwargs["ConditionExpression"] == "#s = :processing"
    assert kwargs["ExpressionAttributeNames"] == {"#s": "status"}
    assert kwargs["ExpressionAttributeValues"][":processing"] == "PROCESSING"


def test_update_job_uses_plain_equality_no_special_case():
    with patch.object(worker, "jobs_table") as mock_table:
        worker.update_job("c1", "j1", "COMPLETED", expected_status="PENDING_UPLOAD")

    _, kwargs = mock_table.update_item.call_args
    assert kwargs["ConditionExpression"] == "#s = :expected_status"
    assert kwargs["ExpressionAttributeValues"][":expected_status"] == "PENDING_UPLOAD"
    assert "IN (" not in kwargs["ConditionExpression"]


# --- Terminal-state writes (COMPLETED/FAILED) must not clobber a job that was
# --- reclaimed by another worker mid-flight (matches the SIGTERM/retry-revert
# --- conditioning already applied at those other call sites in main()).


def test_completed_write_denied_when_job_no_longer_owned(mock_jobs_table):
    mock_jobs_table.put_item(
        Item={"client_id": "c1", "job_id": "j1", "status": "PENDING_UPLOAD"}
    )

    completed = worker.update_job(
        "c1",
        "j1",
        "COMPLETED",
        result_summary="done",
        expected_status="PROCESSING",
    )

    assert completed is False
    item = mock_jobs_table.get_item(Key={"client_id": "c1", "job_id": "j1"})["Item"]
    assert item["status"] == "PENDING_UPLOAD"


def test_completed_write_succeeds_when_still_owned(mock_jobs_table):
    mock_jobs_table.put_item(
        Item={"client_id": "c1", "job_id": "j1", "status": "PROCESSING"}
    )

    completed = worker.update_job(
        "c1",
        "j1",
        "COMPLETED",
        result_summary="done",
        expected_status="PROCESSING",
    )

    assert completed is True
    item = mock_jobs_table.get_item(Key={"client_id": "c1", "job_id": "j1"})["Item"]
    assert item["status"] == "COMPLETED"


def test_failed_write_denied_when_job_no_longer_owned(mock_jobs_table):
    mock_jobs_table.put_item(
        Item={"client_id": "c1", "job_id": "j1", "status": "COMPLETED"}
    )

    failed = worker.update_job(
        "c1",
        "j1",
        "FAILED",
        result_summary="Document processing failed",
        expected_status="PROCESSING",
    )

    assert failed is False
    item = mock_jobs_table.get_item(Key={"client_id": "c1", "job_id": "j1"})["Item"]
    assert item["status"] == "COMPLETED"


def test_failed_write_succeeds_when_still_owned(mock_jobs_table):
    mock_jobs_table.put_item(
        Item={"client_id": "c1", "job_id": "j1", "status": "PROCESSING"}
    )

    failed = worker.update_job(
        "c1",
        "j1",
        "FAILED",
        result_summary="Document processing failed",
        expected_status="PROCESSING",
    )

    assert failed is True
    item = mock_jobs_table.get_item(Key={"client_id": "c1", "job_id": "j1"})["Item"]
    assert item["status"] == "FAILED"


# --- Behavioral: run the built expressions against a real DynamoDB engine (moto) ---


def test_two_acquires_on_same_fresh_lease_second_fails(mock_jobs_table):
    mock_jobs_table.put_item(
        Item={"client_id": "c1", "job_id": "j1", "status": "PENDING_UPLOAD"}
    )

    first = worker.acquire_job_lock("c1", "j1")
    second = worker.acquire_job_lock("c1", "j1")

    assert first is True
    assert second is False


def test_acquire_succeeds_after_lease_aged_past_now(mock_jobs_table):
    mock_jobs_table.put_item(
        Item={
            "client_id": "c1",
            "job_id": "j1",
            "status": "PROCESSING",
            "lock_expires_at": int(time.time()) - 100,
        }
    )

    acquired = worker.acquire_job_lock("c1", "j1")

    assert acquired is True


def test_acquire_denied_while_lease_still_live(mock_jobs_table):
    mock_jobs_table.put_item(
        Item={
            "client_id": "c1",
            "job_id": "j1",
            "status": "PROCESSING",
            "lock_expires_at": int(time.time()) + 500,
        }
    )

    acquired = worker.acquire_job_lock("c1", "j1")

    assert acquired is False


def test_acquire_treats_legacy_processing_without_lease_as_reclaimable(mock_jobs_table):
    """Records mid-flight before this deploy have no lock_expires_at at all -
    they must remain reclaimable, matching the prior behavior."""
    mock_jobs_table.put_item(
        Item={"client_id": "c1", "job_id": "j1", "status": "PROCESSING"}
    )

    acquired = worker.acquire_job_lock("c1", "j1")

    assert acquired is True


def test_acquire_raises_when_record_missing(mock_jobs_table):
    with pytest.raises(worker.JobRecordMissingError):
        worker.acquire_job_lock("c1", "does-not-exist")


def test_acquire_denied_when_record_present_with_live_lease(mock_jobs_table):
    """Distinguishes 'no record at all' (JobRecordMissingError) from 'record
    exists but another worker holds a live lease' (False, no exception)."""
    mock_jobs_table.put_item(
        Item={
            "client_id": "c1",
            "job_id": "j1",
            "status": "PROCESSING",
            "lock_expires_at": int(time.time()) + 500,
        }
    )

    acquired = worker.acquire_job_lock("c1", "j1")

    assert acquired is False


def test_extend_job_lock_only_applies_while_processing(mock_jobs_table):
    mock_jobs_table.put_item(
        Item={"client_id": "c1", "job_id": "j1", "status": "COMPLETED"}
    )

    # A record that already moved on must not be touched, and the caller
    # must be told the lock is no longer held so it stops processing.
    with pytest.raises(worker.LockLostError):
        worker.extend_job_lock("c1", "j1")

    item = mock_jobs_table.get_item(Key={"client_id": "c1", "job_id": "j1"})["Item"]
    assert "lock_expires_at" not in item


def test_extend_job_lock_pushes_lease_forward(mock_jobs_table):
    mock_jobs_table.put_item(
        Item={
            "client_id": "c1",
            "job_id": "j1",
            "status": "PROCESSING",
            "lock_expires_at": int(time.time()) + 10,
        }
    )

    worker.extend_job_lock("c1", "j1")

    item = mock_jobs_table.get_item(Key={"client_id": "c1", "job_id": "j1"})["Item"]
    assert (
        item["lock_expires_at"]
        >= int(time.time()) + worker.settings.VISIBILITY_TIMEOUT_SECONDS - 2
    )


# --- SIGTERM handler ---


@pytest.fixture(autouse=True)
def _reset_active_job():
    worker.active_job.update(
        {"client_id": None, "job_id": None, "receipt_handle": None}
    )
    yield
    worker.active_job.update(
        {"client_id": None, "job_id": None, "receipt_handle": None}
    )


def test_sigterm_leaves_completed_record_untouched_and_skips_visibility_reset(
    mock_jobs_table,
):
    mock_jobs_table.put_item(
        Item={"client_id": "c1", "job_id": "j1", "status": "COMPLETED"}
    )
    worker.active_job.update(
        {"client_id": "c1", "job_id": "j1", "receipt_handle": "rh-1"}
    )

    with (
        patch.object(worker.sqs, "change_message_visibility") as mock_visibility,
        pytest.raises(SystemExit) as exc_info,
    ):
        worker.handle_sigterm()

    assert exc_info.value.code == 0
    mock_visibility.assert_not_called()

    item = mock_jobs_table.get_item(Key={"client_id": "c1", "job_id": "j1"})["Item"]
    assert item["status"] == "COMPLETED"


def test_sigterm_reverts_processing_record_and_resets_visibility(mock_jobs_table):
    mock_jobs_table.put_item(
        Item={"client_id": "c1", "job_id": "j1", "status": "PROCESSING"}
    )
    worker.active_job.update(
        {"client_id": "c1", "job_id": "j1", "receipt_handle": "rh-1"}
    )

    with (
        patch.object(worker.sqs, "change_message_visibility") as mock_visibility,
        pytest.raises(SystemExit) as exc_info,
    ):
        worker.handle_sigterm()

    assert exc_info.value.code == 0
    mock_visibility.assert_called_once_with(
        QueueUrl=worker.settings.SQS_QUEUE_URL,
        ReceiptHandle="rh-1",
        VisibilityTimeout=0,
    )

    item = mock_jobs_table.get_item(Key={"client_id": "c1", "job_id": "j1"})["Item"]
    assert item["status"] == "PENDING_UPLOAD"
