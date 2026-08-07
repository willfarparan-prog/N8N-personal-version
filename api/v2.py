"""Consolidated V2 API entrypoint to stay within Vercel Hobby function limits."""
import importlib
import http.server

from api._lib.http_helpers import get_query_params, send_json


_HANDLERS = {
    "providers": "api.providers",
    "publications": "api.publications",
    "uploads": "api.uploads",
    "batches": "api.batches",
    "provider_events": "api.provider_events",
    "brand_kits": "api.brand_kits",
    "models": "api.models",
    "embed": "api.embed",
    "assets": "api.assets",
    "cleanup_assets": "api.cron.cleanup_assets",
}


class handler(http.server.BaseHTTPRequestHandler):
    def _delegate(self, method: str):
        target = get_query_params(self).get("handler")
        module_name = _HANDLERS.get(target or "")
        if not module_name:
            send_json(self, 404, {"error": "unknown V2 API handler"})
            return
        try:
            target_handler = importlib.import_module(module_name).handler
            getattr(target_handler, method)(self)
        except Exception as exc:
            send_json(self, 500, {"error": f"V2 API dispatch failed: {exc}"})

    def do_GET(self): self._delegate("do_GET")
    def do_POST(self): self._delegate("do_POST")
    def do_PATCH(self): self._delegate("do_PATCH")
    def do_DELETE(self): self._delegate("do_DELETE")
