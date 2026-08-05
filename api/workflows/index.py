"""
List and create workflows.
Routes:
- GET /api/workflows: list workflows (without large graph_json)
- POST /api/workflows: create new workflow
"""
import http.server
from datetime import datetime, timezone

from api._lib.auth import is_authed
from api._lib.http_helpers import read_json_body, send_json
from api._lib.supabase_client import get_client


class handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        """GET /api/workflows - list workflows"""
        if not is_authed(self):
            send_json(self, 401, {"error": "not authenticated"})
            return

        try:
            result = (
                get_client()
                .table("workflows")
                .select("id, name, is_active, created_at, updated_at")
                .order("updated_at", desc=True)
                .execute()
            )
            send_json(self, 200, {"workflows": result.data})
        except Exception as exc:
            send_json(self, 500, {"error": str(exc)})

    def do_POST(self):
        """POST /api/workflows - create workflow"""
        if not is_authed(self):
            send_json(self, 401, {"error": "not authenticated"})
            return

        body = read_json_body(self)
        name = body.get("name")

        if not name:
            send_json(self, 400, {"error": "name is required"})
            return

        now = datetime.now(timezone.utc).isoformat()
        insert_data = {
            "name": name,
            "graph_json": body.get("graph_json", {"nodes": [], "links": []}),
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }

        try:
            result = get_client().table("workflows").insert(insert_data).execute()
            send_json(self, 201, {"workflow": result.data[0]})
        except Exception as exc:
            send_json(self, 500, {"error": str(exc)})
