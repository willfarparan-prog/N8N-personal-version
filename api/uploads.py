"""Issues short-lived private Storage upload URLs; file bytes never traverse Vercel."""
import secrets
from urllib.parse import urlparse
import http.server

from api._lib.auth import is_authed
from api._lib.http_helpers import read_json_body, send_json
from api._lib.supabase_client import get_client

_BUCKETS = {"brand": "flowforge-brand-assets", "batch": "flowforge-batch-inputs"}
_MIMES = {"image/png", "image/jpeg", "image/webp", "text/csv"}

class handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if not is_authed(self): send_json(self, 401, {"error": "not authenticated"}); return
        body = read_json_body(self); kind = body.get("kind"); mime = body.get("mime_type")
        if kind not in _BUCKETS or mime not in _MIMES: send_json(self, 400, {"error": "unsupported upload type"}); return
        if kind == "brand" and mime not in {"image/png", "image/jpeg", "image/webp"}: send_json(self, 400, {"error": "Brand assets must be PNG, JPEG, or WebP"}); return
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "text/csv": ".csv"}[mime]
        path = f"pending/{secrets.token_urlsafe(24)}{suffix}"
        try:
            signed = get_client().storage.from_(_BUCKETS[kind]).create_signed_upload_url(path)
            # supabase-py's key casing for this call has varied across versions
            # (signed_url / signedUrl / signedURL) — normalize to one stable
            # field so the frontend never has to guess.
            signed_url = signed.get("signed_url") or signed.get("signedUrl") or signed.get("signedURL")
            token = signed.get("token")
            send_json(self, 201, {"bucket": _BUCKETS[kind], "path": path, "signed_url": signed_url, "token": token})
        except Exception as exc: send_json(self, 500, {"error": str(exc)})
