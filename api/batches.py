"""Authenticated batch orchestration and polling endpoints."""
import copy
import csv
import io
from datetime import datetime, timezone
from urllib.parse import urlparse
import http.server

from api._lib.auth import is_authed
from api._lib.batch_csv import BatchCsvError, parse_batch_csv
from api._lib.http_helpers import get_query_params, read_json_body, send_json
from api._lib.job_queue import cancel_job, enqueue_job
from api._lib.supabase_client import get_client

def _parts(req): return [p for p in urlparse(req.path).path.split("/") if p]

class handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if not is_authed(self): send_json(self, 401, {"error": "not authenticated"}); return
        parts, body, sb = _parts(self), read_json_body(self), get_client()
        workflow_id = get_query_params(self).get("id") or (parts[2] if len(parts) > 2 else None)
        if ((len(parts) == 4 and parts[:2] == ["api", "workflows"] and parts[3] == "batches") or get_query_params(self).get("action") == "create") and workflow_id:
            upload_path = body.get("input_storage_path")
            if not upload_path: send_json(self, 400, {"error": "input_storage_path from signed upload is required"}); return
            if not isinstance(upload_path, str) or not upload_path.startswith("pending/") or not upload_path.endswith(".csv"):
                send_json(self, 400, {"error": "invalid batch upload path"}); return
            try:
                raw_csv = sb.storage.from_("flowforge-batch-inputs").download(upload_path)
                headers, rows = parse_batch_csv(raw_csv)
            except BatchCsvError as exc: send_json(self, 400, {"error": str(exc)}); return
            except Exception as exc: send_json(self, 400, {"error": f"batch upload could not be read: {exc}"}); return
            workflow_result = sb.table("workflows").select("graph_json").eq("id", workflow_id).single().execute().data
            graph = copy.deepcopy(workflow_result["graph_json"])
            if not any(node.get("type") == "trigger/batch_input" for node in graph.get("nodes", [])):
                send_json(self, 400, {"error": "workflow requires a Batch Input trigger before creating a batch"}); return
            batch = sb.table("batch_runs").insert({"workflow_id": workflow_id, "graph_snapshot": graph, "input_storage_path": upload_path, "status": "queued", "concurrency": min(int(body.get("concurrency", 3)), 3)}).execute().data[0]
            created = []
            for index, row in enumerate(rows, start=1):
                execution = sb.table("executions").insert({"workflow_id": workflow_id, "batch_run_id": batch["id"], "status": "queued", "trigger_type": "batch", "input_json": row, "graph_snapshot": graph}).execute().data[0]
                item = sb.table("batch_items").insert({"batch_run_id": batch["id"], "row_index": index, "raw_input": row, "normalized_input": row, "execution_id": execution["id"], "status": "queued"}).execute().data[0]
                enqueue_job(sb, "execute_workflow", execution["id"], batch_item_id=item["id"], payload={"graph_snapshot": graph, "input": row}, idempotency_key=f"batch:{batch['id']}:row:{index}")
                created.append(item["id"])
            sb.table("batch_runs").update({"status": "running"}).eq("id", batch["id"]).execute()
            send_json(self, 201, {"batch": batch, "headers": headers, "item_count": len(created)}); return
        batch_id = get_query_params(self).get("id") or (parts[2] if len(parts) > 2 else None)
        action = get_query_params(self).get("action") or (parts[3] if len(parts) > 3 else None)
        if batch_id and action == "cancel":
            sb.table("batch_runs").update({"status": "cancel_requested"}).eq("id", batch_id).execute()
            for item in sb.table("batch_items").select("id,execution_id").eq("batch_run_id", batch_id).eq("status", "queued").execute().data:
                sb.table("batch_items").update({"status": "canceled"}).eq("id", item["id"]).execute()
                sb.table("executions").update({"status": "canceled", "cancel_requested_at": datetime.now(timezone.utc).isoformat()}).eq("id", item["execution_id"]).execute()
            send_json(self, 200, {"ok": True}); return
        if batch_id and action == "retry":
            item_id = body.get("item_id")
            item_result = sb.table("batch_items").select("*").eq("id", item_id).eq("batch_run_id", batch_id).eq("status", "failed").execute()
            if not item_result.data: send_json(self, 404, {"error": "failed batch item not found"}); return
            item = item_result.data[0]; batch = sb.table("batch_runs").select("workflow_id,graph_snapshot").eq("id", batch_id).single().execute().data; execution = sb.table("executions").insert({"workflow_id": batch["workflow_id"], "batch_run_id": batch_id, "batch_item_id": item_id, "status": "queued", "trigger_type": "batch", "input_json": item["normalized_input"], "graph_snapshot": batch["graph_snapshot"]}).execute().data[0]
            sb.table("batch_items").update({"execution_id": execution["id"], "status": "queued", "error": None}).eq("id", item_id).execute()
            enqueue_job(sb, "execute_workflow", execution["id"], batch_item_id=item_id, payload={"graph_snapshot": batch["graph_snapshot"], "input": item["normalized_input"]}, idempotency_key=f"retry:{item_id}:{execution['id']}")
            send_json(self, 202, {"execution_id": execution["id"]}); return
        send_json(self, 404, {"error": "not found"})

    def do_GET(self):
        if not is_authed(self): send_json(self, 401, {"error": "not authenticated"}); return
        parts, sb = _parts(self), get_client(); batch_id = get_query_params(self).get("id") or (parts[2] if len(parts) > 2 else None)
        if not batch_id: send_json(self, 400, {"error": "batch id required"}); return
        batch = sb.table("batch_runs").select("*").eq("id", batch_id).single().execute().data
        items = sb.table("batch_items").select("*").eq("batch_run_id", batch_id).order("row_index").execute().data
        if get_query_params(self).get("action") == "csv":
            out = io.StringIO(); writer = csv.DictWriter(out, fieldnames=["row_index", "status", "execution_id", "actual_cost_usd", "output_json", "error"]); writer.writeheader(); writer.writerows(items)
            data = out.getvalue().encode(); self.send_response(200); self.send_header("Content-Type", "text/csv"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        send_json(self, 200, {"batch": batch, "items": items})
