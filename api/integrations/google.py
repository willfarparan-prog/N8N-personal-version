"""Google Drive connection status and disconnect endpoint."""
from http.server import BaseHTTPRequestHandler

from api._lib.auth import is_authed
from api._lib.google_oauth import GoogleOAuthError, connection_status, disconnect
from api._lib.http_helpers import send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not is_authed(self):
            return send_json(self, 401, {"error": "Unauthorized"})
        try:
            return send_json(self, 200, {"google": connection_status()})
        except Exception:
            return send_json(self, 500, {"error": "Could not read Google connection status."})

    def do_DELETE(self):
        if not is_authed(self):
            return send_json(self, 401, {"error": "Unauthorized"})
        try:
            disconnect()
            return send_json(self, 200, {"ok": True})
        except GoogleOAuthError as exc:
            return send_json(self, 400, {"error": str(exc)})
        except Exception:
            return send_json(self, 500, {"error": "Could not disconnect Google."})
