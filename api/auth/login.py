import http.server

from api._lib.auth import check_password, create_session_cookie_value, COOKIE_NAME
from api._lib.http_helpers import read_json_body, send_json


class handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            body = read_json_body(self)

            if "password" not in body or not isinstance(body["password"], str):
                send_json(self, 400, {"error": "password is required"})
                return

            if not check_password(body["password"]):
                send_json(self, 401, {"error": "invalid password"})
                return

            cookie_value = f"{COOKIE_NAME}={create_session_cookie_value()}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=2592000"
            send_json(self, 200, {"ok": True}, extra_headers={"Set-Cookie": cookie_value})

        except Exception as e:
            send_json(self, 400, {"error": f"Failed to process login request: {str(e)}"})
