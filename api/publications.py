"""Owner and unlisted Capsule publication endpoints in one Vercel function."""
import copy
import hashlib
import math
import secrets
from datetime import datetime, timezone
from urllib.parse import urlparse
import http.server

from api._lib.auth import is_authed
from api._lib.engine import run_execution
from api._lib.http_helpers import get_query_params, read_json_body, send_json
from api._lib.secrets import get_node_secrets
from api._lib.supabase_client import get_client

def _hash(token): return hashlib.sha256(token.encode()).hexdigest()
def _token(): return secrets.token_urlsafe(32)
def _parts(req): return [p for p in urlparse(req.path).path.split("/") if p]

def _estimated_cost_usd(graph: dict) -> float:
    """Use owner-authored graph metadata only; public callers never set quota cost."""
    total = 0.0
    for node in graph.get("nodes", []):
        node_type = str(node.get("type", ""))
        if not node_type.startswith("action/"):
            continue
        raw = (node.get("properties") or {}).get("estimated_cost_usd", 0.10)
        try:
            estimate = float(raw)
        except (TypeError, ValueError):
            estimate = 0.10
        # A bad owner-side setting cannot make public quota enforcement weaker.
        total += estimate if math.isfinite(estimate) and estimate >= 0 else 0.10
    return round(total, 6)

class handler(http.server.BaseHTTPRequestHandler):
    def _publication(self, token):
        result = get_client().table("publications").select("*").eq("token_hash", _hash(token)).eq("status", "active").execute()
        return result.data[0] if result.data else None

    def do_GET(self):
        parts = _parts(self)
        query = get_query_params(self)
        if (parts[:2] == ["api", "public"] and len(parts) == 5 and parts[3] == "executions") or query.get("action") == "execution":
            token, execution_id = (parts[2], parts[4]) if len(parts) == 5 else (query.get("token", ""), query.get("execution_id", ""))
            publication = self._publication(token)
            if not publication: send_json(self, 404, {"error": "publication not found"}); return
            execution = get_client().table("executions").select("id,status").eq("id", execution_id).eq("publication_id", publication["id"]).execute().data
            if not execution: send_json(self, 404, {"error": "execution not found"}); return
            row = execution[0]
            # Only an explicit Capsule Result is ever returned publicly. This
            # avoids leaking raw provider payloads, graph configuration, logs,
            # credentials, or another publication's result.
            logs = get_client().table("execution_logs").select("output_json").eq("execution_id", execution_id).eq("node_type", "destination/capsule_result").eq("status", "success").execute().data
            send_json(self, 200, {"execution": {"id": row["id"], "status": row["status"], "result": logs[-1]["output_json"] if logs else None}}, {"Referrer-Policy": "no-referrer"}); return
        if (parts[:2] == ["api", "public"] and len(parts) == 4 and parts[3] == "config") or query.get("action") == "config":
            publication = self._publication(parts[2] if len(parts) == 4 else query.get("token", ""))
            if not publication: send_json(self, 404, {"error": "publication not found"}); return
            workflow = get_client().table("workflows").select("graph_json").eq("id", publication["workflow_id"]).single().execute().data
            capsule = (workflow.get("graph_json", {}).get("flowforge", {}).get("capsule", {}) or {})
            send_json(self, 200, {"publication": {"name": publication["name"], "description": publication.get("description"), "settings": publication["settings_json"]}, "capsule": {"controls": capsule.get("controls", [])}} , {"Referrer-Policy": "no-referrer"}); return
        if not is_authed(self): send_json(self, 401, {"error": "not authenticated"}); return
        send_json(self, 404, {"error": "not found"})

    def do_POST(self):
        parts, body = _parts(self), read_json_body(self)
        query = get_query_params(self)
        if (parts[:2] == ["api", "public"] and len(parts) == 4 and parts[3] == "run") or query.get("action") == "run":
            publication = self._publication(parts[2] if len(parts) == 4 else query.get("token", ""))
            if not publication: send_json(self, 404, {"error": "publication not found"}); return
            workflow = get_client().table("workflows").select("graph_json").eq("id", publication["workflow_id"]).single().execute().data
            graph = copy.deepcopy(workflow["graph_json"]); controls = {(str(c.get("nodeId")), c.get("key")) for c in graph.get("flowforge", {}).get("capsule", {}).get("controls", []) if isinstance(c, dict)}
            for node in graph.get("nodes", []):
                for key, value in (body.get("controls", {}).get(str(node.get("id")), {}) or {}).items():
                    if (str(node.get("id")), key) in controls: node.setdefault("properties", {})[key] = value
            estimated_cost = _estimated_cost_usd(graph)
            # Atomic limits must be enforced before an execution is created.
            accepted = get_client().rpc("accept_flowforge_publication_run", {"p_publication_id": publication["id"], "p_estimated_cost": estimated_cost}).execute().data
            if not accepted: send_json(self, 429, {"error": "publication_limit"}); return
            execution = get_client().table("executions").insert({"workflow_id": publication["workflow_id"], "publication_id": publication["id"], "status": "queued", "trigger_type": "public", "graph_snapshot": graph, "estimated_cost_usd": estimated_cost}).execute().data[0]
            trigger = next((n for n in graph.get("nodes", []) if n.get("type", "").startswith("trigger/")), None)
            if trigger: run_execution(execution["id"], graph, get_node_secrets(), seed_outputs={trigger["id"]: body.get("inputs", {})})
            send_json(self, 202, {"execution_id": execution["id"]}, {"Referrer-Policy": "no-referrer"}); return
        if not is_authed(self): send_json(self, 401, {"error": "not authenticated"}); return
        if (len(parts) == 4 and parts[:2] == ["api", "workflows"] and parts[3] == "publications") or get_query_params(self).get("action") == "create":
            workflow_id = parts[2] if len(parts) == 4 else get_query_params(self).get("id")
            token = _token(); row = get_client().table("publications").insert({"workflow_id": workflow_id, "token_hash": _hash(token), "name": body.get("name", "Untitled Capsule"), "description": body.get("description"), "allowed_origins": body.get("allowed_origins", ["self"]), "settings_json": body.get("settings", {})}).execute().data[0]
            send_json(self, 201, {"publication": row, "token": token}); return
        if get_query_params(self).get("action") == "rotate":
            publication_id = get_query_params(self).get("id"); token = _token()
            result = get_client().table("publications").update({"token_hash": _hash(token), "status": "active", "revoked_at": None, "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", publication_id).execute()
            if not result.data: send_json(self, 404, {"error": "publication not found"}); return
            send_json(self, 200, {"publication": result.data[0], "token": token}); return
        send_json(self, 404, {"error": "not found"})

    def do_PATCH(self):
        if not is_authed(self): send_json(self, 401, {"error": "not authenticated"}); return
        publication_id = get_query_params(self).get("id")
        if not publication_id: send_json(self, 400, {"error": "publication id required"}); return
        body = read_json_body(self); allowed = {"name", "description", "allowed_origins", "runs_per_hour", "daily_cost_limit_usd", "settings_json"}
        update = {key: body[key] for key in allowed if key in body}; update["updated_at"] = datetime.now(timezone.utc).isoformat()
        if not update or len(update) == 1: send_json(self, 400, {"error": "nothing to update"}); return
        try: send_json(self, 200, {"publication": get_client().table("publications").update(update).eq("id", publication_id).execute().data[0]})
        except (IndexError, Exception) as exc: send_json(self, 404, {"error": str(exc)})

    def do_DELETE(self):
        if not is_authed(self): send_json(self, 401, {"error": "not authenticated"}); return
        publication_id = get_query_params(self).get("id")
        if not publication_id: send_json(self, 400, {"error": "publication id required"}); return
        result = get_client().table("publications").update({"status": "revoked", "revoked_at": datetime.now(timezone.utc).isoformat(), "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", publication_id).execute()
        if not result.data: send_json(self, 404, {"error": "publication not found"}); return
        send_json(self, 200, {"ok": True})
