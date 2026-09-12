import hashlib
import hmac
import json
import os
import socket
import sys
from botocore.exceptions import BotoCoreError, ClientError
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("API_KEYS_TABLE", "test-api-keys")
os.environ.setdefault("JOBS_TABLE", "test-jobs")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

import webhook_consumer as wc  # noqa: E402


def _addrinfo(*ips):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]


def test_rejects_non_https_scheme():
    with pytest.raises(wc.WebhookURLValidationError):
        wc._validate_webhook_url("http://example.com/hook")


def test_rejects_missing_host():
    with pytest.raises(wc.WebhookURLValidationError):
        wc._validate_webhook_url("https:///hook")


@pytest.mark.parametrize(
    "ip",
    [
        "169.254.169.254",  # cloud metadata
        "127.0.0.1",  # loopback
        "10.0.0.5",  # RFC1918
        "192.168.1.1",  # RFC1918
        "0.0.0.0",  # unspecified
        "224.0.0.1",  # multicast
        "::1",  # IPv6 loopback
        "fc00::1",  # IPv6 unique local
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
    ],
)
def test_rejects_literal_disallowed_ips(ip):
    with pytest.raises(wc.WebhookURLValidationError):
        wc._validate_webhook_url(f"https://{ip}/hook")


def test_accepts_literal_public_ip():
    wc._validate_webhook_url("https://8.8.8.8/hook")


def test_rejects_hostname_resolving_to_private_ip():
    with patch.object(wc.socket, "getaddrinfo", return_value=_addrinfo("10.1.2.3")):
        with pytest.raises(wc.WebhookURLValidationError):
            wc._validate_webhook_url("https://internal.example.com/hook")


def test_rejects_hostname_when_any_resolved_ip_is_disallowed():
    with patch.object(
        wc.socket, "getaddrinfo", return_value=_addrinfo("8.8.8.8", "169.254.169.254")
    ):
        with pytest.raises(wc.WebhookURLValidationError):
            wc._validate_webhook_url("https://mixed.example.com/hook")


def test_accepts_hostname_resolving_to_public_ips():
    with patch.object(
        wc.socket, "getaddrinfo", return_value=_addrinfo("8.8.8.8", "1.1.1.1")
    ):
        wc._validate_webhook_url("https://public.example.com/hook")


def test_rejects_unresolvable_hostname():
    with patch.object(
        wc.socket, "getaddrinfo", side_effect=socket.gaierror("no such host")
    ):
        with pytest.raises(wc.WebhookURLValidationError):
            wc._validate_webhook_url("https://nowhere.example.com/hook")


def test_no_redirect_handler_blocks_redirects():
    handler = wc._NoRedirectHandler()
    assert (
        handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example")
        is None
    )


# --- get_webhook_config ---


def test_get_webhook_config_returns_config_for_active_client():
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {
            "client_id": "c1",
            "active": True,
            "webhook_url": "https://example.com/hook",
            "webhook_secret": "shh",
        }
    }

    config = wc.get_webhook_config(table, "c1")

    assert config == {
        "webhook_url": "https://example.com/hook",
        "webhook_secret": "shh",
    }
    table.get_item.assert_called_once_with(Key={"client_id": "c1"})


def test_get_webhook_config_returns_none_for_inactive_client():
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {"client_id": "c1", "active": False, "webhook_url": "https://x"}
    }

    assert wc.get_webhook_config(table, "c1") is None


def test_get_webhook_config_returns_none_when_missing():
    table = MagicMock()
    table.get_item.return_value = {}

    assert wc.get_webhook_config(table, "c1") is None


def test_get_webhook_config_swallows_client_error():
    table = MagicMock()
    table.get_item.side_effect = ClientError(
        {"Error": {"Code": "InternalServerError", "Message": "boom"}}, "GetItem"
    )

    assert wc.get_webhook_config(table, "c1") is None


def test_get_webhook_config_swallows_botocore_error():
    table = MagicMock()
    table.get_item.side_effect = BotoCoreError()

    assert wc.get_webhook_config(table, "c1") is None


def test_get_webhook_config_swallows_generic_exception():
    table = MagicMock()
    table.get_item.side_effect = RuntimeError("unexpected")

    assert wc.get_webhook_config(table, "c1") is None


# --- get_job_summary ---


def test_get_job_summary_returns_summary_when_present():
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {"client_id": "c1", "job_id": "j1", "result_summary": "the summary"}
    }

    assert wc.get_job_summary(table, "c1", "j1") == "the summary"
    table.get_item.assert_called_once_with(Key={"client_id": "c1", "job_id": "j1"})


def test_get_job_summary_falls_back_when_summary_missing():
    table = MagicMock()
    table.get_item.return_value = {"Item": {"client_id": "c1", "job_id": "j1"}}

    assert wc.get_job_summary(table, "c1", "j1") == "No summary available"


def test_get_job_summary_returns_none_when_item_absent():
    table = MagicMock()
    table.get_item.return_value = {}

    assert wc.get_job_summary(table, "c1", "j1") is None


def test_get_job_summary_swallows_client_error():
    table = MagicMock()
    table.get_item.side_effect = ClientError(
        {"Error": {"Code": "InternalServerError", "Message": "boom"}}, "GetItem"
    )

    assert wc.get_job_summary(table, "c1", "j1") is None


def test_get_job_summary_swallows_botocore_error():
    table = MagicMock()
    table.get_item.side_effect = BotoCoreError()

    assert wc.get_job_summary(table, "c1", "j1") is None


def test_get_job_summary_swallows_generic_exception():
    table = MagicMock()
    table.get_item.side_effect = RuntimeError("unexpected")

    assert wc.get_job_summary(table, "c1", "j1") is None


# --- lambda_handler ---


def _record(client_id="c1", job_id="j1", message_id="m1"):
    return {
        "messageId": message_id,
        "body": json.dumps({"client_id": client_id, "job_id": job_id}),
    }


def test_lambda_handler_skips_malformed_message_no_failure():
    event = {"Records": [{"messageId": "m1", "body": json.dumps({"client_id": "c1"})}]}

    with (
        patch.object(wc, "get_webhook_config") as mock_config,
        patch.object(wc, "get_job_summary") as mock_summary,
        patch.object(wc, "send_webhook_notification") as mock_send,
    ):
        result = wc.lambda_handler(event, None)

    assert result == {"batchItemFailures": []}
    mock_config.assert_not_called()
    mock_summary.assert_not_called()
    mock_send.assert_not_called()


def test_lambda_handler_skips_when_no_webhook_config():
    event = {"Records": [_record()]}

    with (
        patch.object(wc, "get_webhook_config", return_value=None),
        patch.object(wc, "get_job_summary") as mock_summary,
        patch.object(wc, "send_webhook_notification") as mock_send,
    ):
        result = wc.lambda_handler(event, None)

    assert result == {"batchItemFailures": []}
    mock_summary.assert_not_called()
    mock_send.assert_not_called()


def test_lambda_handler_skips_when_missing_webhook_url_or_secret():
    event = {"Records": [_record()]}

    with (
        patch.object(
            wc,
            "get_webhook_config",
            return_value={"webhook_url": None, "webhook_secret": "shh"},
        ),
        patch.object(wc, "get_job_summary") as mock_summary,
        patch.object(wc, "send_webhook_notification") as mock_send,
    ):
        result = wc.lambda_handler(event, None)

    assert result == {"batchItemFailures": []}
    mock_summary.assert_not_called()
    mock_send.assert_not_called()


def test_lambda_handler_skips_when_summary_missing():
    event = {"Records": [_record()]}

    with (
        patch.object(
            wc,
            "get_webhook_config",
            return_value={
                "webhook_url": "https://example.com/hook",
                "webhook_secret": "shh",
            },
        ),
        patch.object(wc, "get_job_summary", return_value=None),
        patch.object(wc, "send_webhook_notification") as mock_send,
    ):
        result = wc.lambda_handler(event, None)

    assert result == {"batchItemFailures": []}
    mock_send.assert_not_called()


def test_lambda_handler_success_path_calls_send():
    event = {"Records": [_record()]}

    with (
        patch.object(
            wc,
            "get_webhook_config",
            return_value={
                "webhook_url": "https://example.com/hook",
                "webhook_secret": "shh",
            },
        ),
        patch.object(wc, "get_job_summary", return_value="a summary"),
        patch.object(wc, "send_webhook_notification") as mock_send,
    ):
        result = wc.lambda_handler(event, None)

    assert result == {"batchItemFailures": []}
    mock_send.assert_called_once_with(
        "https://example.com/hook", "shh", "c1", "j1", "a summary"
    )


def test_lambda_handler_collaborator_exception_yields_batch_item_failure():
    event = {"Records": [_record(message_id="m-err")]}

    with (
        patch.object(
            wc,
            "get_webhook_config",
            return_value={
                "webhook_url": "https://example.com/hook",
                "webhook_secret": "shh",
            },
        ),
        patch.object(wc, "get_job_summary", return_value="a summary"),
        patch.object(
            wc, "send_webhook_notification", side_effect=RuntimeError("delivery failed")
        ),
    ):
        result = wc.lambda_handler(event, None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "m-err"}]}


def test_lambda_handler_multi_record_partial_failure():
    event = {
        "Records": [
            _record(client_id="c1", job_id="j1", message_id="m-ok"),
            _record(client_id="c2", job_id="j2", message_id="m-fail"),
        ]
    }

    with (
        patch.object(
            wc,
            "get_webhook_config",
            return_value={
                "webhook_url": "https://example.com/hook",
                "webhook_secret": "shh",
            },
        ),
        patch.object(wc, "get_job_summary", return_value="a summary"),
        patch.object(
            wc,
            "send_webhook_notification",
            side_effect=[True, RuntimeError("delivery failed")],
        ),
    ):
        result = wc.lambda_handler(event, None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "m-fail"}]}


# --- send_webhook_notification ---


class _FakeHTTPResponse:
    def __init__(self, status):
        self._status = status

    def getcode(self):
        return self._status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _FakeOpener:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.last_request = None

    def open(self, req, timeout=None):
        self.last_request = req
        if self._exc is not None:
            raise self._exc
        return self._response


def test_send_webhook_notification_success_sends_correct_signature():
    fake_opener = _FakeOpener(response=_FakeHTTPResponse(200))

    with patch.object(wc.urllib.request, "build_opener", return_value=fake_opener):
        result = wc.send_webhook_notification(
            "https://8.8.8.8/hook", "secret123", "c1", "j1", "a summary"
        )

    assert result is True
    sent_req = fake_opener.last_request
    expected_signature = hmac.new(
        b"secret123", sent_req.data, hashlib.sha256
    ).hexdigest()
    assert sent_req.get_header("X-secureagents-signature") == expected_signature
    assert json.loads(sent_req.data) == {
        "event": "JOB_COMPLETED",
        "client_id": "c1",
        "job_id": "j1",
        "status": "COMPLETED",
        "summary": "a summary",
    }


def test_send_webhook_notification_non_2xx_raises():
    fake_opener = _FakeOpener(response=_FakeHTTPResponse(500))

    with patch.object(wc.urllib.request, "build_opener", return_value=fake_opener):
        with pytest.raises(Exception):
            wc.send_webhook_notification(
                "https://8.8.8.8/hook", "secret123", "c1", "j1", "a summary"
            )


def test_send_webhook_notification_validation_failure_skips_build_opener():
    with patch.object(wc.urllib.request, "build_opener") as mock_build_opener:
        with pytest.raises(wc.WebhookURLValidationError):
            wc.send_webhook_notification(
                "https://10.0.0.5/hook", "secret123", "c1", "j1", "a summary"
            )

    mock_build_opener.assert_not_called()


def test_send_webhook_notification_pins_connection_to_validated_ip_dns_rebinding():
    """Regression test for the DNS-rebinding TOCTOU: the hostname must be
    resolved exactly once, and the raw TCP connect must target the IP that
    was actually validated - not whatever a second, independent resolution
    at connect time might return (e.g. an attacker flipping DNS to a
    private/link-local address between validation and connect)."""
    with (
        patch.object(
            wc.socket,
            "getaddrinfo",
            side_effect=[_addrinfo("8.8.8.8"), _addrinfo("169.254.169.254")],
        ) as mock_getaddrinfo,
        patch.object(
            wc.socket,
            "create_connection",
            side_effect=RuntimeError("stop before real network I/O"),
        ) as mock_create_connection,
    ):
        with pytest.raises(RuntimeError):
            wc.send_webhook_notification(
                "https://rebind.example.com/hook", "secret123", "c1", "j1", "a summary"
            )

    mock_getaddrinfo.assert_called_once()
    mock_create_connection.assert_called_once()
    connect_address = mock_create_connection.call_args[0][0]
    assert connect_address[0] == "8.8.8.8"
