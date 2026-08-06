"""Receives Google's OAuth callback, stores the encrypted refresh token, and returns to Integrations."""
from http.server import BaseHTTPRequestHandler
from urllib.parse import quote

from api._lib.google_oauth import GoogleOAuthError, exchange_and_store
from api._lib.http_helpers import get_query_params


def _redirect(req, target: str):
    req.send_response(302)
    req.send_header("Location", target)
    req.end_headers()


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = get_query_params(self)
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
