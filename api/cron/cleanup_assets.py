"""Daily cleanup for Flow Forge's seven-day transient assets."""
from datetime import datetime, timedelta, timezone
import http.server

from api._lib.auth import check_cron_secret
from api._lib.http_helpers import send_json
from api._lib.supabase_client import get_client

class handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if not check_cron_secret(self): send_json(self, 401, {"error": "invalid cron secret"}); return
        sb = get_client(); now_dt = datetime.now(timezone.utc); now = now_dt.isoformat(); removed = 0
        try:
            assets = sb.table("generated_assets").select("id,storage_path").eq("is_persistent", False).lt("expires_at", now).execute().data
            paths = [asset["storage_path"] for asset in assets if asset.get("storage_path")]
            if paths: sb.storage.from_("flowforge-assets").remove(paths)
            if assets: sb.table("generated_assets").delete().in_("id", [asset["id"] for asset in assets]).execute()
            removed = len(assets)
            old_batches = sb.table("batch_runs").select("input_storage_path").lt("created_at", (now_dt - timedelta(days=7)).isoformat()).execute().data
            batch_paths = [row["input_storage_path"] for row in old_batches if row.get("input_storage_path")]
            if batch_paths: sb.storage.from_("flowforge-batch-inputs").remove(batch_paths)
            send_json(self, 200, {"removed": removed, "batch_uploads_removed": len(batch_paths), "at": now})
        except Exception as exc: send_json(self, 500, {"error": str(exc), "removed": removed})
