import json
import time
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app import main as worker


def _s3_message(key="c1/uploads/j1/doc.pdf", receipt="rh-1"):
    return {
        "ReceiptHandle": receipt,
        "Body": json.dumps(
            {
                "Records": [
                    {"s3": {"bucket": {"name": "bucket"}, "object": {"key": key}}}
                ]
            }
        ),
    }


def _s3_message_multi(keys, receipt="rh-1"):
    return {
        "ReceiptHandle": receipt,
        "Body": json.dumps(
            {
                "Records": [
                    {"s3": {"bucket": {"name": "bucket"}, "object": {"key": key}}}
                    for key in keys
                ]
            }
        ),
    }


@pytest.fixture
def driven_worker(monkeypatch):
    """Drives worker.main() through exactly one SQS message, then stops the loop."""
    fake_sqs = MagicMock()
    state = {"polls": 0}

    def receive_message(**kwargs):
        state["polls"] += 1
        if state["polls"] == 1:
            return {"Messages": [_s3_message()]}
        worker.shutdown_flag = True
        return {"Messages": []}

    fake_sqs.receive_message.side_effect = receive_message
    monkeypatch.setattr(worker, "sqs", fake_sqs)
    monkeypatch.setattr(worker, "shutdown_flag", False)
    monkeypatch.setattr(worker, "write_heartbeat", lambda: None)
    yield fake_sqs
    worker.shutdown_flag = False


def _seed_pending(table):
    table.put_item(Item={"client_id": "c1", "job_id": "j1", "status": "PENDING_UPLOAD"})


def _get(table):
    return table.get_item(Key={"client_id": "c1", "job_id": "j1"})["Item"]


def _get_job(table, client_id, job_id):
    return table.get_item(Key={"client_id": client_id, "job_id": job_id})["Item"]


def test_value_error_marks_failed_and_deletes_message(driven_worker, mock_jobs_table):
    _seed_pending(mock_jobs_table)

    with patch.object(
        worker, "process_document", side_effect=ValueError("PDF is empty")
    ):
        worker.main()

    item = _get(mock_jobs_table)
    assert item["status"] == "FAILED"
    assert "Document rejected: PDF is empty" in item["result_summary"]
    driven_worker.delete_message.assert_called_once_with(
        QueueUrl=worker.settings.SQS_QUEUE_URL, ReceiptHandle="rh-1"
    )


def test_generic_exception_leaves_row_and_message_for_redrive(
    driven_worker, mock_jobs_table
):
    _seed_pending(mock_jobs_table)

    with patch.object(
        worker, "process_document", side_effect=RuntimeError("infra blip")
    ):
        worker.main()

    item = _get(mock_jobs_table)
    assert item["status"] == "PROCESSING"  # lock held, no terminal write
    assert "result_summary" not in item
    driven_worker.delete_message.assert_not_called()


def test_client_error_reverts_to_pending_and_keeps_message(
    driven_worker, mock_jobs_table
):
    _seed_pending(mock_jobs_table)
    err = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "Converse"
    )

    with patch.object(worker, "process_document", side_effect=err):
        worker.main()

    item = _get(mock_jobs_table)
    assert item["status"] == "PENDING_UPLOAD"
    driven_worker.delete_message.assert_not_called()


def test_malformed_bedrock_response_goes_to_redrive_not_failed(
    driven_worker, mock_jobs_table, monkeypatch
):
    _seed_pending(mock_jobs_table)

    monkeypatch.setattr(
        worker, "extract_text_from_s3_pdf", lambda bucket, key: "some legal text"
    )
    monkeypatch.setattr(worker, "extend_sqs_visibility", lambda *a, **k: None)
    monkeypatch.setattr(worker, "extend_job_lock", lambda *a, **k: None)

    fake_bedrock = MagicMock()
    fake_bedrock.converse.return_value = {"output": {}}  # missing message/content
    monkeypatch.setattr(worker, "bedrock", fake_bedrock)

    worker.main()

    item = _get(mock_jobs_table)
    assert item["status"] == "PROCESSING"
    assert "result_summary" not in item
    driven_worker.delete_message.assert_not_called()


def test_happy_path_completes_job_and_deletes_message(driven_worker, mock_jobs_table):
    _seed_pending(mock_jobs_table)

    with patch.object(
        worker, "process_document", return_value=("a clean summary", False)
    ):
        worker.main()

    item = _get(mock_jobs_table)
    assert item["status"] == "COMPLETED"
    assert item["result_summary"] == "a clean summary"
    driven_worker.delete_message.assert_called_once_with(
        QueueUrl=worker.settings.SQS_QUEUE_URL, ReceiptHandle="rh-1"
    )


def test_truncated_summary_gets_exact_prefix_with_single_space(
    driven_worker, mock_jobs_table
):
    _seed_pending(mock_jobs_table)

    with patch.object(
        worker, "process_document", return_value=("the rest of the summary", True)
    ):
        worker.main()

    item = _get(mock_jobs_table)
    assert item["status"] == "COMPLETED"
    assert item["result_summary"] == (
        f"[Note: document was truncated to {worker.settings.CHAR_LIMIT} characters] "
        "the rest of the summary"
    )


def test_multi_record_sqs_message_processes_both_jobs_one_delete(
    driven_worker, mock_jobs_table
):
    mock_jobs_table.put_item(
        Item={"client_id": "c1", "job_id": "j1", "status": "PENDING_UPLOAD"}
    )
    mock_jobs_table.put_item(
        Item={"client_id": "c1", "job_id": "j2", "status": "PENDING_UPLOAD"}
    )

    state = {"polls": 0}

    def receive_message(**kwargs):
        state["polls"] += 1
        if state["polls"] == 1:
            return {
                "Messages": [
                    _s3_message_multi(
                        ["c1/uploads/j1/doc.pdf", "c1/uploads/j2/doc.pdf"]
                    )
                ]
            }
        worker.shutdown_flag = True
        return {"Messages": []}

    driven_worker.receive_message.side_effect = receive_message

    with patch.object(
        worker,
        "process_document",
        side_effect=[("summary 1", False), ("summary 2", False)],
    ):
        worker.main()

    item1 = _get_job(mock_jobs_table, "c1", "j1")
    item2 = _get_job(mock_jobs_table, "c1", "j2")
    assert item1["status"] == "COMPLETED"
    assert item1["result_summary"] == "summary 1"
    assert item2["status"] == "COMPLETED"
    assert item2["result_summary"] == "summary 2"
    driven_worker.delete_message.assert_called_once_with(
        QueueUrl=worker.settings.SQS_QUEUE_URL, ReceiptHandle="rh-1"
    )


def test_job_record_missing_skips_delete_without_unhandled_exception(
    driven_worker, mock_jobs_table
):
    # No row seeded for c1/j1, so acquire_job_lock raises JobRecordMissingError.
    worker.main()

    driven_worker.delete_message.assert_not_called()


def test_lock_denied_skip_still_deletes_message_without_processing(
    driven_worker, mock_jobs_table
):
    mock_jobs_table.put_item(
        Item={
            "client_id": "c1",
            "job_id": "j1",
            "status": "PROCESSING",
            "lock_expires_at": int(time.time()) + 500,
        }
    )

    with patch.object(worker, "process_document") as mock_process:
        worker.main()

    mock_process.assert_not_called()
    driven_worker.delete_message.assert_called_once_with(
        QueueUrl=worker.settings.SQS_QUEUE_URL, ReceiptHandle="rh-1"
    )


# --- Phase 1b regression: lock lease must be extended before SQS visibility,
# --- and a failed lock extension must abort processing rather than leave SQS
# --- visibility extended without a confirmed lock (duplicate-processing risk).


def test_extend_job_lock_called_before_extend_sqs_visibility(mock_jobs_table):
    mock_jobs_table.put_item(
        Item={"client_id": "c1", "job_id": "j1", "status": "PROCESSING"}
    )
    call_order = []

    with (
        patch.object(
            worker,
            "extend_job_lock",
            side_effect=lambda *a, **k: call_order.append("lock"),
        ),
        patch.object(
            worker,
            "extend_sqs_visibility",
            side_effect=lambda *a, **k: call_order.append("visibility"),
        ),
        patch.object(worker, "extract_text_from_s3_pdf", return_value="legal text"),
        patch.object(worker, "bedrock") as mock_bedrock,
    ):
        mock_bedrock.converse.return_value = {
            "output": {"message": {"content": [{"text": "a summary"}]}}
        }
        worker.process_document("c1", "j1", "bucket", "key", "rh-1")

    assert call_order == ["lock", "visibility", "lock", "visibility"]


def test_process_document_aborts_without_extending_visibility_when_lock_lost(
    mock_jobs_table,
):
    mock_jobs_table.put_item(
        Item={"client_id": "c1", "job_id": "j1", "status": "PENDING_UPLOAD"}
    )

    with (
        patch.object(
            worker, "extend_job_lock", side_effect=worker.LockLostError("lock lost")
        ),
        patch.object(worker, "extend_sqs_visibility") as mock_extend_visibility,
    ):
        with pytest.raises(worker.LockLostError):
            worker.process_document("c1", "j1", "bucket", "key", "rh-1")

    mock_extend_visibility.assert_not_called()


def test_lock_lost_during_processing_leaves_row_and_message_untouched(
    driven_worker, mock_jobs_table
):
    _seed_pending(mock_jobs_table)

    with (
        patch.object(
            worker, "extend_job_lock", side_effect=worker.LockLostError("lock lost")
        ),
        patch.object(worker, "extend_sqs_visibility") as mock_extend_visibility,
    ):
        worker.main()

    mock_extend_visibility.assert_not_called()
    item = _get(mock_jobs_table)
    # Row stays PROCESSING: no PENDING_UPLOAD revert, since another worker may
    # already hold the lock and be actively processing it.
    assert item["status"] == "PROCESSING"
    driven_worker.delete_message.assert_not_called()
