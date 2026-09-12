import os
import json
import logging
import urllib.request
import ipaddress
import socket
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


_no_redirect_opener = urllib.request.build_opener(_NoRedirectHandler)


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


def _validate_webhook_url(url: str) -> None:
    """Validates a client-configured webhook URL before it is called, to block SSRF against internal infrastructure"""
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
        return

    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise WebhookURLValidationError(
            f"Could not resolve webhook host {hostname}: {e}"
        ) from e

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


def send_webhook_notification(url, secret_key, client_id, job_id, summary):
    """Sends a POST request to the client's webhook URL"""
    _validate_webhook_url(url)

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

    try:
        with _no_redirect_opener.open(req, timeout=10) as response:
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
