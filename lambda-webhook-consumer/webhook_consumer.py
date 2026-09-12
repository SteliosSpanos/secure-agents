import os
import json
import logging
import urllib.request
import http.client
import ipaddress
import socket
import functools
import hmac
import hashlib
import boto3
from urllib.parse import urlparse
from botocore.exceptions import ClientError, BotoCoreError
from botocore.config import Config

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class WebhookURLValidationError(Exception):
    pass


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that connects to a pre-validated IP instead of re-resolving the host.

    The Host header and TLS SNI/certificate hostname checking still use
    ``self.host`` untouched - only the raw TCP connect target is pinned to the
    IP address that was already validated against SSRF blocklists, closing the
    DNS-rebinding TOCTOU window between validation and connect.
    """

    def __init__(self, *args, pinned_ip=None, **kwargs):
        self._pinned_ip = pinned_ip
        super().__init__(*args, **kwargs)

    def connect(self):
        self.sock = socket.create_connection(
            (self._pinned_ip or self.host, self.port), self.timeout, self.source_address
        )
        if self._tunnel_host:
            self._tunnel()
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, pinned_ip):
        super().__init__()
        self._pinned_ip = pinned_ip

    def https_open(self, req):
        return self.do_open(
            functools.partial(_PinnedHTTPSConnection, pinned_ip=self._pinned_ip),
            req,
        )


aws_config = Config(
    retries={"max_attempts": 3, "mode": "standard"},
    connect_timeout=2,
    read_timeout=10,
)


dynamodb = boto3.resource("dynamodb", config=aws_config)

API_KEYS_TABLE_NAME = os.environ.get("API_KEYS_TABLE")
JOBS_TABLE_NAME = os.environ.get("JOBS_TABLE")
if not API_KEYS_TABLE_NAME or not JOBS_TABLE_NAME:
    raise RuntimeError("Critical environment variables are missing.")

api_keys_table = dynamodb.Table(API_KEYS_TABLE_NAME)
jobs_table = dynamodb.Table(JOBS_TABLE_NAME)


def lambda_handler(event, context):
    """
    Processes SQS messages containing job completion info.
    Fetches client webhook URL and job summary, then sends a POST request.
    """
    batch_item_failures = []

    for record in event.get("Records", []):
        message_id = record.get("messageId")
        try:
            message_body = json.loads(record.get("body", "{}"))
            client_id = message_body.get("client_id")
            job_id = message_body.get("job_id")

            if not client_id or not job_id:
                logger.error(
                    "Malformed message: Missing client_id or job_id. MessageID: %s",
                    message_id,
                )
                continue

            webhook_config = get_webhook_config(api_keys_table, client_id)
            if not webhook_config:
                logger.warning(
                    "No active webhook configuration found for client %s. Skipping notification.",
                    client_id,
                )
                continue

            webhook_url = webhook_config.get("webhook_url")
            webhook_secret = webhook_config.get("webhook_secret")

            if not webhook_url or not webhook_secret:
                logger.warning(
                    "Missing webhook_url or webhook_secret for client %s. Skipping notification.",
                    client_id,
                )
                continue

            summary = get_job_summary(jobs_table, client_id, job_id)
            if summary is None:
                logger.warning(
                    "Job %s not found for client %s. Skipping notification.",
                    job_id,
                    client_id,
                )
                continue

            send_webhook_notification(
                webhook_url, webhook_secret, client_id, job_id, summary
            )

            logger.info(
                "Successfully notified client %s for job %s.", client_id, job_id
            )

        except Exception:
            logger.exception("Unexpected error processing SQS record: %s.", message_id)
            batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}


def get_webhook_config(table, client_id):
    """Retrieves the webhook_url for a specific client_id using get_item"""
    try:
        response = table.get_item(Key={"client_id": client_id})
        item = response.get("Item")

        if item and item.get("active", False):
            return {
                "webhook_url": item.get("webhook_url"),
                "webhook_secret": item.get("webhook_secret"),
            }

        return None
    except (ClientError, BotoCoreError):
        logger.exception(
            "Database error while fetching webhook URL for client %s.", client_id
        )
        return None
    except Exception:
        logger.exception(
            "Unexpected error while fetching webhook URL for client %s.", client_id
        )
        return None


def get_job_summary(table, client_id, job_id):
    """Retrieves the result_summary for a specific job"""
    try:
        response = table.get_item(Key={"client_id": client_id, "job_id": job_id})
        item = response.get("Item")

        if item:
            return item.get("result_summary", "No summary available")

        return None
    except (ClientError, BotoCoreError):
        logger.exception("Database error while fetching summary for job %s.", job_id)
        return None
    except Exception:
        logger.exception("Unexpected error while fetching summary for job %s.", job_id)
        return None


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for any IP that shouldn't be reachable from a webhook call"""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _validate_webhook_url(url: str) -> str:
    """Validates a client-configured webhook URL before it is called, to block SSRF against internal infrastructure.

    Returns the validated IP address to pin the outgoing connection to, so the
    connection cannot be re-resolved to a different (potentially internal)
    address after validation (DNS rebinding).
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise WebhookURLValidationError(f"Webhook URL must use https: {url}")

    hostname = parsed.hostname
    if not hostname:
        raise WebhookURLValidationError(f"Webhook URL has no host: {url}")

    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        if _is_blocked_ip(literal_ip):
            raise WebhookURLValidationError(
                f"Webhook URL host is a disallowed IP: {hostname}"
            )
        return str(literal_ip)

    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise WebhookURLValidationError(
            f"Could not resolve webhook host {hostname}: {e}"
        ) from e

    if not resolved:
        raise WebhookURLValidationError(
            f"Webhook host {hostname} did not resolve to any address"
        )

    pinned_ip = None
    for _family, _type, _proto, _canonname, sockaddr in resolved:
        try:
            resolved_ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            raise WebhookURLValidationError(
                f"Webhook host {hostname} resolved to an unparsable address: {sockaddr[0]}"
            )
        if _is_blocked_ip(resolved_ip):
            raise WebhookURLValidationError(
                f"Webhook host {hostname} resolves to a disallowed IP: {resolved_ip}"
            )
        if pinned_ip is None:
            pinned_ip = str(resolved_ip)

    return pinned_ip


def send_webhook_notification(url, secret_key, client_id, job_id, summary):
    """Sends a POST request to the client's webhook URL"""
    pinned_ip = _validate_webhook_url(url)

    payload = {
        "event": "JOB_COMPLETED",
        "client_id": client_id,
        "job_id": job_id,
        "status": "COMPLETED",
        "summary": summary,
    }

    data = json.dumps(payload).encode("utf-8")

    signature = hmac.new(secret_key.encode("utf-8"), data, hashlib.sha256).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-SecureAgents-Signature": signature,
        "X-Webhook-Delivery-ID": f"evt_{job_id}",
    }

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    opener = urllib.request.build_opener(
        _NoRedirectHandler, _PinnedHTTPSHandler(pinned_ip)
    )

    try:
        with opener.open(req, timeout=10) as response:
            status = response.getcode()
            if status >= 200 and status < 300:
                return True
            else:
                logger.error(
                    "Webhook delivery failed with status %d for client %s.",
                    status,
                    client_id,
                )
                raise Exception(f"Webhook returned status {status}")
    except Exception:
        logger.exception("Failed to send webhook to %s.", url)
        raise
