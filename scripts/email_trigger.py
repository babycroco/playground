"""
scripts/email_trigger.py — Inbound email processor for WEG document replies

Polls the Sweet Home Immobilien mailbox via Microsoft Graph for inbound emails
that contain WP/Jahresabrechnung documents from Hausverwaltungen, then updates
data/document_request_log.csv to mark matching requests as "received".

Uses audit/graph_auth.py for MSAL token acquisition.

Run with:
    python3 -m scripts.email_trigger
"""

import os
import sys
import logging
from datetime import datetime, timezone

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.graph_auth import get_graph_token

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH     = os.path.join(BASE_DIR, "data", "document_request_log.csv")
LOGS_DIR     = os.path.join(BASE_DIR, "logs")

os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOGS_DIR, "email_trigger.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Keywords that suggest a document delivery email from an HV
_DELIVERY_KEYWORDS = [
    "wirtschaftsplan", "jahresabrechnung", "betriebskostenabrechnung",
    "hausgeldabrechnung", "wohngeldabrechnung", "einzelabrechnung",
    "im anhang", "anbei", "als anlage", "beigefügt",
]


def _load_request_log() -> pd.DataFrame:
    if os.path.exists(LOG_PATH):
        return pd.read_csv(LOG_PATH, dtype=str)
    return pd.DataFrame(columns=[
        "date", "building_address", "unit_ids", "document_type",
        "year_requested", "hv_name", "hv_email", "status",
    ])


def _save_request_log(df: pd.DataFrame) -> None:
    df.to_csv(LOG_PATH, index=False)


def _is_delivery_email(subject: str, body_preview: str) -> bool:
    """Heuristic: does this email look like a document delivery from an HV?"""
    text = (subject + " " + body_preview).lower()
    return any(kw in text for kw in _DELIVERY_KEYWORDS)


def _normalize_sender(sender_email: str) -> str:
    return sender_email.strip().lower()


def poll_and_update() -> None:
    """
    Poll the mailbox for new emails and update request log for any that
    appear to be WP/document deliveries from known HV contacts.
    """
    mailbox = os.getenv("MICROSOFT_MAILBOX")
    if not mailbox:
        raise RuntimeError("MICROSOFT_MAILBOX not set in .env")

    token = get_graph_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Fetch the 50 most recent inbox messages
    url = (
        f"https://graph.microsoft.com/v1.0/users/{mailbox}/mailFolders/inbox/messages"
        f"?$top=50&$orderby=receivedDateTime desc"
        f"&$select=id,subject,bodyPreview,from,receivedDateTime,isRead"
    )

    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    messages = resp.json().get("value", [])

    log_df   = _load_request_log()
    updated  = 0

    for msg in messages:
        subject      = msg.get("subject", "")
        body_preview = msg.get("bodyPreview", "")
        sender_addr  = (
            msg.get("from", {})
               .get("emailAddress", {})
               .get("address", "")
        )

        if not _is_delivery_email(subject, body_preview):
            continue

        sender_norm = _normalize_sender(sender_addr)

        # Find open requests from this sender
        mask = (
            (log_df["hv_email"].str.strip().str.lower() == sender_norm)
            & (log_df["status"].isin(["sent", "drafted"]))
        )

        if not mask.any():
            logger.debug("Delivery email from %s — no matching open request.", sender_addr)
            continue

        log_df.loc[mask, "status"] = "received"
        updated += mask.sum()
        logger.info(
            "Marked %d request(s) as 'received' for sender %s (subject: %r)",
            int(mask.sum()), sender_addr, subject,
        )

    if updated:
        _save_request_log(log_df)
        print(f"Updated {updated} request(s) to status 'received'.")
    else:
        print("No matching delivery emails found.")


def main() -> int:
    try:
        poll_and_update()
        return 0
    except Exception as exc:
        logger.error("email_trigger failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
