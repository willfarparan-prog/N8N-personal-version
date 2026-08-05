"""
Single workflow CRUD operations.
Routes:
- GET /api/workflows/{id}: get full workflow
- PUT /api/workflows/{id}: partial update
- DELETE /api/workflows/{id}: delete workflow
"""
import http.server
from datetime import datetime, timezone

from api._lib.auth import is_authed
from api._lib.http_helpers import read_json_body, send_json, get_path_param
from api._lib.supabase_client import get_client


class handler(http.server.BaseHTTPRequestHandler):
    def extract_workflow_id(self) -> str | None:
        """Extract workflow ID from URL path"""
        return get_path_param(self, r"/api/workflows/([^/]+)$")

    def do_GET(self):
        """GET /api/workflows/{id} - get workflow"""
        if not is_authed(self):
            send_json(self, 401, {"error": "not authenticated"})
            return

        workflow_id = self.extract_workflow_id()
        if not workflow_id:
            send_json(self, 400, {"error": "workflow id required"})
            return

        try:
            result = (
                get_client()
                .table("workflows")
                .select("*")
                .eq("id", workflow_id)
                .execute()
            )
            if not result.data:
                send_json(self, 404, {"error": "workflow not found"})
            else:
                send_json(self, 200, {"workflow": result.data[0]})
        except Exception as exc:
            send_json(self, 500, {"error": str(exc)})

    def do_PUT(self):
        """PUT /api/workflows/{id} - partial update"""
        if not is_authed(self):
            send_json(self, 401, {"error": "not authenticated"})
            return

        workflow_id = self.extract_workflow_id()
        if not workflow_id:
            send_json(self, 400, {"error": "workflow id required"})
            return

        body = read_json_body(self)
        update_dict = {"updated_at": datetime.now(timezone.utc).isoformat()}

        if "name" in body:
            update_dict["name"] = body["name"]
        if "graph_json" in body:
            update_dict["graph_json"] = body["graph_json"]
        if "is_active" in body:
            update_dict["is_active"] = body["is_active"]

        # Check if there are any actual updates besides updated_at
        if len(update_dict) <= 1:
            send_json(self, 400, {"error": "nothing to update"})
            return

        try:
            result = (
                get_client()
                .table("workflows")
                .update(update_dict)
                .eq("id", workflow_id)
                .execute()
            )
            if not result.data:
                send_json(self, 404, {"error": "workflow not found"})
            else:
                send_json(self, 200, {"workflow": result.data[0]})
        except Exception as exc:
            send_json(self, 500, {"error": str(exc)})

    def do_DELETE(self):
        """DELETE /api/workflows/{id} - delete workflow"""
        if not is_authed(self):
            send_json(self, 401, {"error": "not authenticated"})
            return

        workflow_id = self.extract_workflow_id()
        if not workflow_id:
            send_json(self, 400, {"error": "workflow id required"})
            return

        try:
            get_client().table("workflows").delete().eq("id", workflow_id).execute()
            send_json(self, 200, {"ok": True})
        except Exception as exc:
            send_json(self, 500, {"error": str(exc)})
