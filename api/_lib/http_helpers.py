"""
Shared request/response helpers for Vercel's Python runtime, which expects a
BaseHTTPRequestHandler subclass named `handler` in each api/*.py file (no framework).
Every API route in this project should use read_json_body/send_json/get_cookies for consistency.
"""
import json
import re
from urllib.parse import urlparse, parse_qs


def read_json_body(req) -> dict:
    length = int(req.headers.get("Content-Length", 0) or 0)
    if length == 0:
        return {}
    raw = req.rfile.read(length)
    try:
        return json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return {}


def send_json(req, status: int, payload: dict, extra_headers: dict | None = None):
    body = json.dumps(payload).encode("utf-8")
    req.send_response(status)
    req.send_header("Content-Type", "application/json")
    req.send_header("Content-Length", str(len(body)))
    for k, v in (extra_headers or {}).items():
        req.send_header(k, v)
    req.end_headers()
    req.wfile.write(body)


def get_cookies(req) -> dict[str, str]:
    header = req.headers.get("Cookie") or req.headers.get("cookie") or ""
    cookies = {}
    for part in header.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            cookies[k] = v
    return cookies


def get_query_params(req) -> dict[str, str]:
    parsed = urlparse(req.path)
    return {k: v[0] for k, v in parse_qs(parsed.query).items()}


def get_path_param(req, pattern: str) -> str | None:
    """
    Extract a single dynamic segment, e.g. get_path_param(req, r'/api/workflows/([^/]+)$').

    Vercel's routing (via vercel.json's explicit `routes`, required because this project
    uses `builds`) rewrites the request to the target function with the dynamic segment
    passed as a `?id=...` query param rather than preserving the original path — so the
    regex match against req.path will not fire in production. Fall back to the `id` query
    param in that case; the regex path is kept for clarity/local reasoning and as a safety net.
    """
    parsed = urlparse(req.path)
    match = re.match(pattern, parsed.path)
    if match:
        return match.group(1)
    return get_query_params(req).get("id")
