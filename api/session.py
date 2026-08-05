import http.server

from api._lib.auth import is_authed
from api._lib.http_helpers import send_json


class handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            send_json(self, 200, {"authed": is_authed(self)})
        except Exception as e:
            send_json(self, 400, {"error": f"Failed to get session status: {str(e)}"})
