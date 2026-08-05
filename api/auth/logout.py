import http.server

from api._lib.auth import COOKIE_NAME
from api._lib.http_helpers import send_json


class handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            cookie_value = f"{COOKIE_NAME}=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0"
            send_json(self, 200, {"ok": True}, extra_headers={"Set-Cookie": cookie_value})
        except Exception as e:
            send_json(self, 400, {"error": f"Failed to process logout request: {str(e)}"})
