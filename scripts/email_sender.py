"""
scripts/email_sender.py — Reusable email sender via Microsoft Graph API

Provides send_email() used by request_missing_docs.py and any other script
that needs to send via the Sweet Home Immobilien Outlook mailbox.

Run with:
    python3 -m scripts.email_sender   (self-test / dry-run)
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.graph_auth import get_graph_token

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOGS_DIR, "email_sender.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

_GRAPH_SEND_URL = (
    "https://graph.microsoft.com/v1.0/users/{mailbox}/sendMail"
)


def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = None,
) -> bool:
    """
    Send an email via Microsoft Graph API using the Sweet Home Immobilien mailbox.

    Args:
        to:      recipient email address
        subject: email subject line
        body:    plain-text body (German)
        cc:      optional CC address

    Returns:
        True if sent successfully, False otherwise.

    Logs every attempt to logs/email_sender.log.
    """
    mailbox = os.getenv("MICROSOFT_MAILBOX")
    if not mailbox:
        logger.error("MICROSOFT_MAILBOX not set in .env — cannot send email.")
        return False

    try:
        token = get_graph_token()
    except RuntimeError as exc:
        logger.error("Token acquisition failed: %s", exc)
        return False

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }

    payload: dict = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "Text",
                "content": body,
            },
            "toRecipients": [
                {"emailAddress": {"address": to}}
            ],
        },
        "saveToSentItems": True,
    }

    if cc:
        payload["message"]["ccRecipients"] = [
            {"emailAddress": {"address": cc}}
        ]

    url = _GRAPH_SEND_URL.format(mailbox=mailbox)

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        success = resp.status_code == 202  # Graph returns 202 Accepted on success

        if success:
            logger.info(
                "SENT  to=%s  subject=%r",
                to, subject,
            )
        else:
            logger.error(
                "FAILED  to=%s  subject=%r  status=%d  body=%s",
                to, subject, resp.status_code, resp.text[:300],
            )

        return success

    except requests.RequestException as exc:
        logger.error(
            "FAILED  to=%s  subject=%r  error=%s",
            to, subject, exc,
        )
        return False


if __name__ == "__main__":
    print("email_sender.py loaded OK. Import send_email() to use.")
    print(f"Mailbox configured: {os.getenv('MICROSOFT_MAILBOX', '(not set)')}")
