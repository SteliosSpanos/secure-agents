import json
import os
import sys
from unittest.mock import MagicMock, call

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault(
    "WEBHOOK_QUEUE_URL",
    "https://sqs.eu-central-1.amazonaws.com/123456789012/webhook-queue",
)
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

import webhook_trigger  # noqa: E402


def _completed_record(job_id, seq="100000000000000000001"):
    return {
        "eventID": f"evt-{job_id}",
        "eventName": "MODIFY",
        "dynamodb": {
            "SequenceNumber": seq,
            "ApproximateCreationDateTime": 1700000000,
            "NewImage": {
                "status": {"S": "COMPLETED"},
                "client_id": {"S": "client-1"},
                "job_id": {"S": job_id},
            },
            "OldImage": {"status": {"S": "PROCESSING"}},
        },
    }


@pytest.fixture(autouse=True)
def fake_sqs(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(webhook_trigger, "sqs", client)
    return client


def test_all_success_returns_no_failures(fake_sqs):
    event = {"Records": [_completed_record("job-a"), _completed_record("job-b", "2")]}

    result = webhook_trigger.lambda_handler(event, None)

    assert result == {"batchItemFailures": []}
    assert fake_sqs.send_message.call_count == 2
    fake_sqs.send_message.assert_has_calls(
        [
            call(
                QueueUrl=webhook_trigger.WEBHOOK_QUEUE_URL,
                MessageBody=json.dumps(
                    {
                        "event": "job_completed",
                        "client_id": "client-1",
                        "job_id": "job-a",
                        "timestamp": 1700000000,
                    }
                ),
                MessageAttributes={
                    "MessageType": {
                        "DataType": "String",
                        "StringValue": "JobCompletionNotification",
                    }
                },
            ),
            call(
                QueueUrl=webhook_trigger.WEBHOOK_QUEUE_URL,
                MessageBody=json.dumps(
                    {
                        "event": "job_completed",
                        "client_id": "client-1",
                        "job_id": "job-b",
                        "timestamp": 1700000000,
                    }
                ),
                MessageAttributes={
                    "MessageType": {
                        "DataType": "String",
                        "StringValue": "JobCompletionNotification",
                    }
                },
            ),
        ]
    )


def test_partial_failure_only_reports_failed_record(fake_sqs):
    good = _completed_record("job-good", "seq-good")
    bad = _completed_record("job-bad", "seq-bad")

    def send(*args, **kwargs):
        if "job-bad" in kwargs["MessageBody"]:
            raise RuntimeError("SQS unavailable")

    fake_sqs.send_message.side_effect = send

    result = webhook_trigger.lambda_handler({"Records": [good, bad]}, None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "seq-bad"}]}


def test_missing_sequence_number_is_not_reported(fake_sqs):
    bad = _completed_record("job-bad", "seq-bad")
    del bad["dynamodb"]["SequenceNumber"]
    fake_sqs.send_message.side_effect = RuntimeError("boom")

    result = webhook_trigger.lambda_handler({"Records": [bad]}, None)

    assert result == {"batchItemFailures": []}


def test_non_completed_records_are_skipped(fake_sqs):
    record = _completed_record("job-x")
    record["dynamodb"]["NewImage"]["status"]["S"] = "PROCESSING"

    result = webhook_trigger.lambda_handler({"Records": [record]}, None)

    assert result == {"batchItemFailures": []}
    fake_sqs.send_message.assert_not_called()
