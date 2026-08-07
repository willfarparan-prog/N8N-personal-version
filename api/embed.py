"""Dynamic embed shell with per-publication frame-ancestors CSP."""
import hashlib
from urllib.parse import urlparse
import http.server

from api._lib.supabase_client import get_client
from api._lib.http_helpers import get_query_params

class handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        token = get_query_params(self).get("token")
        if not token: self.send_error(404); return
        publication = get_client().table("publications").select("allowed_origins,status").eq("token_hash", hashlib.sha256(token.encode()).hexdigest()).execute().data
        if not publication or publication[0]["status"] != "active": self.send_error(404); return
        origins = publication[0].get("allowed_origins") or ["self"]
        ancestors = "'self'" if origins == ["self"] else " ".join("'self'" if value == "self" else value for value in origins)
        body = f'<!doctype html><html><head><meta name="referrer" content="no-referrer"><style>html,body,iframe{{width:100%;min-height:720px;border:0;margin:0}}</style></head><body><iframe src="/p/{token}" title="Published Flow Forge Capsule" loading="lazy" referrerpolicy="no-referrer"></iframe><script>addEventListener("message",e=>{{if(e.data&&e.data.type==="flowforge:height")parent.postMessage(e.data,"*")}})</script></body></html>'.encode()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.send_header("Content-Security-Policy", f"frame-ancestors {ancestors}"); self.send_header("Referrer-Policy", "no-referrer"); self.end_headers(); self.wfile.write(body)
