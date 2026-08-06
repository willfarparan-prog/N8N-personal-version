"""
Manually trigger workflow execution.
Route:
- POST /api/workflows/{id}/run: manually execute workflow
"""
import copy
import http.server

from api._lib.auth import is_authed
from api._lib.engine import run_execution
from api._lib.http_helpers import read_json_body, send_json, get_path_param
from api._lib.secrets import get_node_secrets
from api._lib.supabase_client import get_client


class handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        """POST /api/workflows/{id}/run - manually trigger workflow"""
        if not is_authed(self):
            send_json(self, 401, {"error": "not authenticated"})
            return

        workflow_id = get_path_param(self, r"/api/workflows/([^/]+)/run$")
        if not workflow_id:
            send_json(self, 400, {"error": "workflow id required"})
            return

        # Fetch workflow
        try:
            workflow_result = (
                get_client()
                .table("workflows")
                .select("*")
                .eq("id", workflow_id)
                .execute()
            )
            if not workflow_result.data:
                send_json(self, 404, {"error": "workflow not found"})
                return
            workflow = workflow_result.data[0]
        except Exception as exc:
            send_json(self, 500, {"error": str(exc)})
            return

        body = read_json_body(self)
        workflow_graph = copy.deepcopy(workflow["graph_json"])

        # Capsules submit a small, whitelisted set of per-run control changes.
        # They never mutate the saved graph: an operator can vary a prompt or
        # model setting without changing the designer's reusable workflow.
        overrides = body.get("_flowforge_overrides", {}) if isinstance(body, dict) else {}
        if isinstance(overrides, dict):
            nodes_by_id = {str(node.get("id")): node for node in workflow_graph.get("nodes", [])}
            capsule_controls = (workflow_graph.get("flowforge", {}) or {}).get("capsule", {}).get("controls", [])
            allowed_controls = {
                (str(control.get("nodeId")), control.get("key"))
                for control in capsule_controls
                if isinstance(control, dict)
            }
            for node_id, property_overrides in overrides.items():
                node = nodes_by_id.get(str(node_id))
                if node is None or not isinstance(property_overrides, dict):
                    continue
                properties = node.get("properties") or {}
                for key, value in property_overrides.items():
                    # A capsule may only override an existing node property.
                    # This avoids turning the operator interface into an
                    # arbitrary graph-editing surface.
                    if (str(node_id), key) in allowed_controls and key in properties:
                        properties[key] = value
                node["properties"] = properties

        # Create execution record
        try:
            execution_data = {
                "workflow_id": workflow_id,
                "status": "pending",
                "trigger_type": "manual",
                "input_json": body,
            }
            execution_result = (
                get_client().table("executions").insert(execution_data).execute()
            )
            execution_id = execution_result.data[0]["id"]
        except Exception as exc:
            send_json(self, 500, {"error": str(exc)})
            return

        # Find trigger node
        nodes = workflow_graph.get("nodes", [])
        trigger_node = next(
            (node for node in nodes if node.get("type", "").startswith("trigger/")),
            None,
        )

        if not trigger_node:
            try:
                get_client().table("executions").update(
                    {"status": "failed", "error": "no trigger node found"}
                ).eq("id", execution_id).execute()
            except Exception:
                pass  # Best effort
            send_json(self, 400, {"error": "workflow has no trigger node"})
            return

        trigger_node_id = trigger_node["id"]

        # Run execution synchronously - blocks until graph completes/fails/hits
        # pending_external. This is expected/fine for a manual run, Vercel function
        # timeout permitting.
        try:
            run_execution(
                execution_id=execution_id,
                workflow_graph=workflow_graph,
                secrets=get_node_secrets(),
                seed_outputs={trigger_node_id: body},
            )
        except Exception as exc:
            # Safety net: node executors normally catch their own errors, so this
            # shouldn't normally fire. Best-effort mark the execution as failed.
            try:
                get_client().table("executions").update(
                    {"status": "failed", "error": str(exc)}
                ).eq("id", execution_id).execute()
            except Exception:
                pass  # Best effort
            send_json(self, 500, {"error": str(exc)})
            return

        # Re-fetch execution after completion
        try:
            final_result = (
                get_client()
                .table("executions")
                .select("*")
                .eq("id", execution_id)
                .execute()
            )
            send_json(self, 200, {"execution": final_result.data[0]})
        except Exception as exc:
            send_json(self, 500, {"error": str(exc)})
