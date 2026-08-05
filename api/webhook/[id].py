import http.server

from api._lib.http_helpers import read_json_body, send_json, get_path_param
from api._lib.supabase_client import get_client
from api._lib.engine import run_execution
from api._lib.secrets import get_node_secrets


class handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        workflow_id = get_path_param(self, r'/api/webhook/([^/]+)$')
        if not workflow_id:
            send_json(self, 400, {"error": "missing workflow id"})
            return

        try:
            # Fetch workflow
            workflow_result = get_client().table("workflows").select("*").eq("id", workflow_id).execute()
            if not workflow_result.data:
                send_json(self, 404, {"error": "workflow not found"})
                return

            workflow = workflow_result.data[0]
            if not workflow.get("is_active"):
                send_json(self, 403, {"error": "workflow is not active"})
                return

            # Read webhook payload
            body = read_json_body(self)

            # Create execution record
            execution_result = get_client().table("executions").insert({
                "workflow_id": workflow_id,
                "status": "pending",
                "trigger_type": "webhook",
                "input_json": body
            }).execute()
            execution = execution_result.data[0]

            # Find trigger node
            trigger_node = None
            nodes = workflow["graph_json"].get("nodes", [])
            for node in nodes:
                if node.get("type", "").startswith("trigger/"):
                    trigger_node = node
                    break

            if not trigger_node:
                # Mark execution as failed
                get_client().table("executions").update({
                    "status": "failed",
                    "error": "workflow has no trigger node"
                }).eq("id", execution["id"]).execute()
                send_json(self, 400, {"error": "workflow has no trigger node"})
                return

            # Run the execution
            run_execution(
                execution_id=execution["id"],
                workflow_graph=workflow["graph_json"],
                secrets=get_node_secrets(),
                seed_outputs={trigger_node["id"]: body}
            )

            send_json(self, 202, {"execution_id": execution["id"]})

        except Exception as e:
            send_json(self, 500, {"error": str(e)})
