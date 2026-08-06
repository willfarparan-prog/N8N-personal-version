"""Google Drive OAuth endpoints, combined to stay within Vercel Hobby's function limit."""
from http.server import BaseHTTPRequestHandler
from urllib.parse import quote

from api._lib.auth import is_authed
from api._lib.google_oauth import GoogleOAuthError, authorization_url, connection_status, disconnect, exchange_and_store
from api._lib.http_helpers import get_query_params, send_json


def _redirect(req, target: str):
    req.send_response(302)
    req.send_header("Location", target)
    req.end_headers()


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = get_query_params(self)
        action = query.get("action")
        if action == "authorize":
            if not is_authed(self):
                return send_json(self, 401, {"error": "Unauthorized"})
            try:
                url = authorization_url(self)
            except GoogleOAuthError as exc:
                return send_json(self, 400, {"error": str(exc)})
            return _redirect(self, url)
        if action == "callback":
            if query.get("error"):
                return _redirect(self, f"/integrations.html?google=error&message={quote('Google authorization was cancelled or denied.')}")
            code, state = query.get("code"), query.get("state")
            if not code or not state:
                return _redirect(self, f"/integrations.html?google=error&message={quote('Google did not return a connection code.')}")
            try:
                exchange_and_store(self, code, state)
            except GoogleOAuthError as exc:
                return _redirect(self, f"/integrations.html?google=error&message={quote(str(exc))}")
            except Exception:
                return _redirect(self, f"/integrations.html?google=error&message={quote('Could not finish the Google connection. Please try again.')}")
            return _redirect(self, "/integrations.html?google=connected")
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
