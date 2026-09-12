import hashlib
import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from boto3.dynamodb.conditions import Key

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("API_KEYS_TABLE", "test-api-keys")
os.environ.setdefault("ORIGIN_SECRET", "super-secret-origin-value")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

import authorizer  # noqa: E402


def _event(headers):
    return {"headers": headers}


@pytest.fixture(autouse=True)
def fake_table(monkeypatch):
    table = MagicMock()
    monkeypatch.setattr(authorizer, "api_keys_table", table)
    return table


def test_missing_origin_header_denied(fake_table):
    result = authorizer.lambda_handler(_event({}), None)

    assert result == {"isAuthorized": False}
    fake_table.query.assert_not_called()


def test_wrong_origin_header_denied(fake_table):
    result = authorizer.lambda_handler(_event({"x-origin-verify": "wrong-value"}), None)

    assert result == {"isAuthorized": False}
    fake_table.query.assert_not_called()


def test_empty_origin_header_denied(fake_table):
    result = authorizer.lambda_handler(_event({"x-origin-verify": ""}), None)

    assert result == {"isAuthorized": False}


def test_correct_origin_but_missing_api_key_denied(fake_table):
    result = authorizer.lambda_handler(
        _event({"x-origin-verify": "super-secret-origin-value"}), None
    )

    assert result == {"isAuthorized": False}


def test_correct_origin_and_valid_active_key_authorized(fake_table):
    fake_table.query.return_value = {
        "Items": [{"client_id": "client-1", "active": True}]
    }

    result = authorizer.lambda_handler(
        _event(
            {
                "x-origin-verify": "super-secret-origin-value",
                "x-api-key": "some-key",
            }
        ),
        None,
    )

    assert result == {"isAuthorized": True, "context": {"client_id": "client-1"}}
    fake_table.query.assert_called_once_with(
        IndexName="ApiKeyIndex",
        KeyConditionExpression=Key("api_key").eq(
            hashlib.sha256(b"some-key").hexdigest()
        ),
        Limit=1,
    )


def test_correct_origin_but_inactive_key_denied(fake_table):
    fake_table.query.return_value = {
        "Items": [{"client_id": "client-1", "active": False}]
    }

    result = authorizer.lambda_handler(
        _event(
            {
                "x-origin-verify": "super-secret-origin-value",
                "x-api-key": "some-key",
            }
        ),
        None,
    )

    assert result == {"isAuthorized": False}


def test_uses_constant_time_comparison(monkeypatch, fake_table):
    calls = []
    real_compare = authorizer.hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real_compare(a, b)

    monkeypatch.setattr(authorizer.hmac, "compare_digest", spy)

    authorizer.lambda_handler(
        _event({"x-origin-verify": "super-secret-origin-value"}), None
    )

    assert calls == [("super-secret-origin-value", "super-secret-origin-value")]


def test_decimal_active_flag_is_ignored_here(fake_table):
    """Sanity check: active is compared as a plain truthy value, DynamoDB Decimal
    types included, matching table.get_item's behavior elsewhere in the stack."""
    fake_table.query.return_value = {
        "Items": [{"client_id": "client-1", "active": Decimal(1)}]
    }

    result = authorizer.lambda_handler(
        _event(
            {
                "x-origin-verify": "super-secret-origin-value",
                "x-api-key": "some-key",
            }
        ),
        None,
    )

    assert result["isAuthorized"] is True
