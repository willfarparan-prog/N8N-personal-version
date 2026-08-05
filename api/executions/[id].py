import http.server

from api._lib.auth import is_authed
from api._lib.http_helpers import send_json, get_path_param
from api._lib.supabase_client import get_client


class handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if not is_authed(self):
            send_json(self, 401, {"error": "not authenticated"})
            return

        execution_id = get_path_param(self, r'/api/executions/([^/]+)$')
        if not execution_id:
            send_json(self, 400, {"error": "missing execution id"})
            return

        try:
            # Fetch execution
            execution_result = get_client().table("executions").select("*").eq("id", execution_id).execute()
            if not execution_result.data:
                send_json(self, 404, {"error": "execution not found"})
                return

            execution = execution_result.data[0]

            # Fetch logs
            logs_result = get_client().table("execution_logs").select("*").eq("execution_id", execution_id).order("started_at").execute()

            send_json(self, 200, {
                "execution": execution,
                "logs": logs_result.data
            })

        except Exception as e:
            send_json(self, 500, {"error": str(e)})
