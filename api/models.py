"""Authenticated read/update/delete API over trained LoRA models."""
from __future__ import annotations
from datetime import datetime, timezone
import http.server
import uuid

from api._lib.auth import is_authed
from api._lib.http_helpers import get_query_params, read_json_body, send_json
from api._lib.supabase_client import get_client
from api._lib.engine import run_execution
from api._lib.secrets import get_node_secrets

class handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if not is_authed(self): send_json(self, 401, {"error": "not authenticated"}); return
        sb, query = get_client(), get_query_params(self); model_id = query.get("id")
        if model_id:
            try: model = sb.table("trained_loras").select("*").eq("id", model_id).single().execute().data
            except Exception: send_json(self, 404, {"error": "model not found"}); return
            send_json(self, 200, {"model": model}); return
        send_json(self, 200, {"models": sb.table("trained_loras").select("*").order("created_at", desc=True).execute().data})

    def do_POST(self):
        if not is_authed(self): send_json(self, 401, {"error": "not authenticated"}); return
        sb = get_client()
        body = read_json_body(self)

        name = body.get("name")
        trigger_word = body.get("trigger_word", "")
        image_paths = body.get("image_paths")

        if not isinstance(name, str) or not name.strip():
            send_json(self, 400, {"error": "name is required"}); return
        if not isinstance(trigger_word, str):
            send_json(self, 400, {"error": "trigger_word must be a string"}); return
        if not isinstance(image_paths, list) or not (3 <= len(image_paths) <= 30) or not all(isinstance(p, str) and p for p in image_paths):
            send_json(self, 400, {"error": "image_paths must be a list of 3 to 30 storage paths"}); return

        # Download each uploaded training image and zip them in memory.
        import io, zipfile
        buffer = io.BytesIO()
        try:
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for index, path in enumerate(image_paths):
                    try:
                        data = sb.storage.from_("flowforge-brand-assets").download(path)
                    except Exception as exc:
                        send_json(self, 400, {"error": f"could not read uploaded image at '{path}': {exc}"}); return
                    suffix = path.rsplit(".", 1)[-1] if "." in path else "jpg"
                    zf.writestr(f"image_{index:02d}.{suffix}", data)
        except Exception as exc:
            send_json(self, 500, {"error": f"failed to build training archive: {exc}"}); return

        zip_path = f"training-zips/{uuid.uuid4()}.zip"
        try:
            sb.storage.from_("flowforge-brand-assets").upload(zip_path, buffer.getvalue(), {"content-type": "application/zip"})
            signed = sb.storage.from_("flowforge-brand-assets").create_signed_url(zip_path, 3600)
            zip_url = signed.get("signedURL") or signed.get("signedUrl")
        except Exception as exc:
            send_json(self, 500, {"error": f"failed to stage training archive: {exc}"}); return
        if not zip_url:
            send_json(self, 500, {"error": "could not obtain a signed URL for the training archive"}); return

        # Auto-provision a minimal, single-node workflow so this reuses the
        # existing execution + polling + trained_loras registry machinery
        # instead of building a parallel tracking path.
        graph_json = {
            "nodes": [{
                "id": 1,
                "type": "action/fal_train_lora",
                "properties": {
                    "name": name.strip(),
                    "model": "fal-ai/flux-lora-fast-training",
                    "input": {"images_data_url": zip_url, "trigger_word": trigger_word},
                },
            }],
            "links": [],
        }

        try:
            workflow = sb.table("workflows").insert({
                "name": f"LoRA training: {name.strip()}",
                "graph_json": graph_json,
                "is_active": True,
            }).execute().data[0]
            execution = sb.table("executions").insert({
                "workflow_id": workflow["id"],
                "status": "pending",
                "trigger_type": "manual",
                "input_json": {},
            }).execute().data[0]
        except Exception as exc:
            send_json(self, 500, {"error": f"could not create training workflow: {exc}"}); return

        try:
            run_execution(
                execution_id=execution["id"],
                workflow_graph=graph_json,
                secrets=get_node_secrets(),
                start_node_id=1,
            )
        except Exception as exc:
            send_json(self, 500, {"error": f"training submission failed: {exc}", "workflow_id": workflow["id"], "execution_id": execution["id"]}); return

        try:
            final_execution = sb.table("executions").select("status,error").eq("id", execution["id"]).single().execute().data
        except Exception:
            final_execution = {}
        if final_execution.get("status") == "failed":
            send_json(self, 502, {"error": final_execution.get("error") or "training submission failed", "workflow_id": workflow["id"], "execution_id": execution["id"]}); return

        try:
            model = sb.table("trained_loras").select("*").eq("source_execution_id", execution["id"]).single().execute().data
        except Exception:
            model = None

        send_json(self, 201, {
            "model": model,
            "workflow_id": workflow["id"],
            "execution_id": execution["id"],
            "warning": None if model else "Training was submitted but could not be immediately confirmed in the model registry — check execution history.",
        })

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
