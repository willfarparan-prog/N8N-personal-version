"""Single-shared-password auth: sign/verify a session cookie. No DB, no user accounts."""
import hmac
import os

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

COOKIE_NAME = "flowforge_session"
MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(os.environ["COOKIE_SECRET"], salt="flowforge-session")


def check_password(submitted: str) -> bool:
    return hmac.compare_digest(submitted, os.environ["APP_PASSWORD"])


def create_session_cookie_value() -> str:
    return _serializer().dumps({"authed": True})


def verify_session_cookie(cookie_value: str | None) -> bool:
    if not cookie_value:
        return False
    try:
        data = _serializer().loads(cookie_value, max_age=MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return False
    return bool(data.get("authed"))


def is_authed(req) -> bool:
    """req is a BaseHTTPRequestHandler instance; checks its Cookie header."""
    from api._lib.http_helpers import get_cookies
    return verify_session_cookie(get_cookies(req).get(COOKIE_NAME))


def check_cron_secret(req) -> bool:
    """For /api/cron/* routes, called by Supabase pg_net instead of a browser — no cookie involved."""
    provided = req.headers.get("X-Cron-Secret") or req.headers.get("x-cron-secret")
    expected = os.environ.get("CRON_SECRET")
    return bool(expected) and hmac.compare_digest(provided or "", expected)
