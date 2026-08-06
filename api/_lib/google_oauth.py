"""Server-side Google OAuth and Drive token helpers.

FlowForge is intentionally a server-side OAuth client: browser code never sees
the client secret, refresh token, or a usable Google access token. The app is a
single personal workspace today, so its Google connection is stored under the
fixed ``google`` provider key and is accessible only to the service-role API.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from api._lib.auth import COOKIE_NAME, is_authed
from api._lib.http_helpers import get_cookies
from api._lib.supabase_client import get_client

GOOGLE_PROVIDER = "google"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleOAuthError(RuntimeError):
    """A safe, user-facing failure to connect or use Google."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_serializer() -> URLSafeTimedSerializer:
    secret = os.environ.get("COOKIE_SECRET")
    if not secret:
        raise GoogleOAuthError("FlowForge session configuration is missing.")
    return URLSafeTimedSerializer(secret, salt="flowforge-google-oauth-state")


def _cipher() -> Fernet:
    key = os.environ.get("GOOGLE_TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise GoogleOAuthError("Google token encryption is not configured yet.")
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise GoogleOAuthError("Google token encryption configuration is invalid.") from exc


def _config() -> dict[str, str]:
    config = {
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        "redirect_uri": os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", ""),
    }
    if not all(config.values()):
        raise GoogleOAuthError("Google OAuth is not configured yet. Add the Google client ID, client secret, and redirect URL in Vercel.")
    return config


def google_is_configured() -> bool:
    return bool(
        os.environ.get("GOOGLE_CLIENT_ID")
        and os.environ.get("GOOGLE_CLIENT_SECRET")
        and os.environ.get("GOOGLE_OAUTH_REDIRECT_URI")
        and os.environ.get("GOOGLE_TOKEN_ENCRYPTION_KEY")
    )


def _session_fingerprint(req) -> str:
    cookie = get_cookies(req).get(COOKIE_NAME, "")
    return hashlib.sha256(cookie.encode("utf-8")).hexdigest()


def authorization_url(req) -> str:
    if not is_authed(req):
        raise GoogleOAuthError("Sign in to FlowForge before connecting Google.")
    config = _config()
    state = _state_serializer().dumps({
        "nonce": secrets.token_urlsafe(24),
        "session": _session_fingerprint(req),
    })
    query = urlencode({
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    })
    return f"{AUTH_URL}?{query}"


def _connection() -> dict[str, Any] | None:
    response = (
        get_client()
        .table("oauth_connections")
        .select("provider, encrypted_refresh_token, scopes, token_metadata, updated_at")
        .eq("provider", GOOGLE_PROVIDER)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def connection_status() -> dict[str, Any]:
    connection = _connection()
    return {
        "configured": google_is_configured(),
        "connected": bool(connection),
        "scopes": (connection or {}).get("scopes") or [],
        "updated_at": (connection or {}).get("updated_at"),
    }


def exchange_and_store(req, code: str, state: str) -> None:
    if not is_authed(req):
        raise GoogleOAuthError("Your FlowForge session expired. Please sign in and connect Google again.")
    try:
        state_data = _state_serializer().loads(state, max_age=600)
    except (BadSignature, SignatureExpired) as exc:
        raise GoogleOAuthError("Google connection request expired. Start the connection again.") from exc
    if not secrets.compare_digest(state_data.get("session", ""), _session_fingerprint(req)):
        raise GoogleOAuthError("Google connection request did not match this FlowForge session.")

    config = _config()
    try:
        response = httpx.post(TOKEN_URL, data={
            "code": code,
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "redirect_uri": config["redirect_uri"],
            "grant_type": "authorization_code",
        }, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GoogleOAuthError("Google did not complete the authorization exchange. Please try connecting again.") from exc

    refresh_token = payload.get("refresh_token")
    existing = _connection()
    if not refresh_token and existing:
        encrypted_refresh_token = existing["encrypted_refresh_token"]
    elif refresh_token:
        encrypted_refresh_token = _cipher().encrypt(refresh_token.encode("utf-8")).decode("utf-8")
    else:
        raise GoogleOAuthError("Google did not return a reusable connection. Please approve access and try again.")

    scopes = str(payload.get("scope") or " ".join(GOOGLE_SCOPES)).split()
    get_client().table("oauth_connections").upsert({
        "provider": GOOGLE_PROVIDER,
        "encrypted_refresh_token": encrypted_refresh_token,
        "scopes": scopes,
        "token_metadata": {"token_type": payload.get("token_type", "Bearer")},
        "updated_at": _now(),
    }, on_conflict="provider").execute()


def disconnect() -> None:
    """Remove the locally held encrypted token. Google authorization can be revoked separately in Google Account settings."""
    get_client().table("oauth_connections").delete().eq("provider", GOOGLE_PROVIDER).execute()


def google_access_token() -> str:
    connection = _connection()
    if not connection:
        raise GoogleOAuthError("Connect Google Drive in Integrations before running this node.")
    try:
        refresh_token = _cipher().decrypt(connection["encrypted_refresh_token"].encode("utf-8")).decode("utf-8")
    except (InvalidToken, KeyError, TypeError) as exc:
        raise GoogleOAuthError("FlowForge could not read the Google connection. Reconnect Google Drive.") from exc

    config = _config()
    try:
        response = httpx.post(TOKEN_URL, data={
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }, timeout=20)
        response.raise_for_status()
        access_token = response.json().get("access_token")
    except (httpx.HTTPError, ValueError) as exc:
        raise GoogleOAuthError("Google access expired or was revoked. Reconnect Google Drive.") from exc
    if not access_token:
        raise GoogleOAuthError("Google did not return an access token. Reconnect Google Drive.")
    return access_token
