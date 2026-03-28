"""
audit/graph_auth.py — Shared Microsoft Graph authentication

Provides a single get_graph_token() function used by both
email_trigger.py and email_sender.py. Reads credentials from .env
via python-dotenv. Never modifies .env.
"""

import os
import logging

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_GRAPH_SCOPE = "https://graph.microsoft.com/.default"


def get_graph_token() -> str:
    """
    Obtain a Microsoft Graph access token using MSAL client credentials flow.

    Required .env variables:
        MICROSOFT_CLIENT_ID      — Azure AD app registration client ID
        MICROSOFT_TENANT_ID      — Azure AD tenant ID
        MICROSOFT_CLIENT_SECRET  — app client secret

    Returns:
        str — bearer access token

    Raises:
        RuntimeError if credentials are missing or token acquisition fails.
    """
    try:
        import msal
    except ImportError as exc:
        raise RuntimeError(
            "msal package not installed. Run: pip install msal"
        ) from exc

    client_id     = os.getenv("MICROSOFT_CLIENT_ID")
    tenant_id     = os.getenv("MICROSOFT_TENANT_ID")
    client_secret = os.getenv("MICROSOFT_CLIENT_SECRET")

    missing = [k for k, v in {
        "MICROSOFT_CLIENT_ID":     client_id,
        "MICROSOFT_TENANT_ID":     tenant_id,
        "MICROSOFT_CLIENT_SECRET": client_secret,
    }.items() if not v]

    if missing:
        raise RuntimeError(
            f"Missing required .env variables: {', '.join(missing)}"
        )

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=client_secret,
    )

    result = app.acquire_token_for_client(scopes=[_GRAPH_SCOPE])

    if "access_token" not in result:
        error     = result.get("error", "unknown")
        error_desc = result.get("error_description", "no description")
        raise RuntimeError(
            f"Failed to acquire Graph token: {error} — {error_desc}"
        )

    logger.debug("Graph token acquired successfully.")
    return result["access_token"]
