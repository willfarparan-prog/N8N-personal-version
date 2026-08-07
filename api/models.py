"""Authenticated read/update/delete API over trained LoRA models."""
from __future__ import annotations
from datetime import datetime, timezone
import http.server

from api._lib.auth import is_authed
from api._lib.http_helpers import get_query_params, read_json_body, send_json
from api._lib.supabase_client import get_client

class handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if not is_authed(self): send_json(self, 401, {"error": "not authenticated"}); return
        sb, query = get_client(), get_query_params(self); model_id = query.get("id")
        if model_id:
            try: model = sb.table("trained_loras").select("*").eq("id", model_id).single().execute().data
            except Exception: send_json(self, 404, {"error": "model not found"}); return
            send_json(self, 200, {"model": model}); return
        send_json(self, 200, {"models": sb.table("trained_loras").select("*").order("created_at", desc=True).execute().data})

    def do_PATCH(self):
        if not is_authed(self): send_json(self, 401, {"error": "not authenticated"}); return
        sb, query = get_client(), get_query_params(self); model_id = query.get("id")
        if not model_id: send_json(self, 400, {"error": "missing id"}); return
        body = read_json_body(self)
        update: dict = {}
        if "name" in body:
            if not isinstance(body["name"], str) or not body["name"]: send_json(self, 400, {"error": "name must be a non-empty string"}); return
            update["name"] = body["name"]
        if "trigger_word" in body:
            if not isinstance(body["trigger_word"], str): send_json(self, 400, {"error": "trigger_word must be a string"}); return
            update["trigger_word"] = body["trigger_word"]
        if not update: send_json(self, 400, {"error": "nothing to update"}); return
        update["updated_at"] = datetime.now(timezone.utc).isoformat()
        try: result = sb.table("trained_loras").update(update).eq("id", model_id).execute()
        except Exception as exc: send_json(self, 500, {"error": f"update failed: {exc}"}); return
        if not result.data: send_json(self, 404, {"error": "model not found"}); return
        send_json(self, 200, {"model": result.data[0]}); return

    def do_DELETE(self):
        if not is_authed(self): send_json(self, 401, {"error": "not authenticated"}); return
        query = get_query_params(self); model_id = query.get("id")
        if not model_id: send_json(self, 400, {"error": "missing id"}); return
        sb = get_client()
        try: sb.table("trained_loras").delete().eq("id", model_id).execute()
        except Exception as exc: send_json(self, 500, {"error": f"delete failed: {exc}"}); return
        send_json(self, 200, {"deleted": True}); return
