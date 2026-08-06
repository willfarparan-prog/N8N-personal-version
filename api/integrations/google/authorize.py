"""Starts the server-side Google OAuth authorization-code flow."""
from http.server import BaseHTTPRequestHandler

from api._lib.auth import is_authed
from api._lib.google_oauth import GoogleOAuthError, authorization_url
from api._lib.http_helpers import send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not is_authed(self):
            return send_json(self, 401, {"error": "Unauthorized"})
        try:
            url = authorization_url(self)
        except GoogleOAuthError as exc:
            return send_json(self, 400, {"error": str(exc)})
        self.send_response(302)
        self.send_header("Location", url)
        self.end_headers()
