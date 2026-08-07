"""Idempotent provider callback receiver; only signed callbacks are accepted."""
import hashlib
import hmac
import os
import base64
import json
import time
from types import SimpleNamespace
import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
from urllib.parse import urlparse
import http.server

from api._lib.http_helpers import get_query_params, send_json
from api._lib.supabase_client import get_client
from api._lib.engine import resume_execution
from api._lib.secrets import get_node_secrets
from api._lib.nodes.openrouter_media import _archive, _usage


def _graph_for(sb, execution_id):
    execution = sb.table("executions").select("workflow_id,graph_snapshot").eq("id", execution_id).single().execute().data
    return execution.get("graph_snapshot") or sb.table("workflows").select("graph_json").eq("id", execution["workflow_id"]).single().execute().data["graph_json"]


def complete_openrouter_video(sb, log, data):
    """Archive a completed private provider video before the graph resumes."""
    urls = data.get("unsigned_urls") or []
    if not urls:
        raise ValueError("OpenRouter video completion omitted content URL")
    key = get_node_secrets().get("OPENROUTER_API_KEY")
    response = httpx.get(urls[0], headers={"Authorization": f"Bearer {key}"}, timeout=120)
    response.raise_for_status()
    mime = response.headers.get("content-type", "video/mp4").split(";", 1)[0]
    ctx = SimpleNamespace(execution_id=log["execution_id"], node_id=log["node_id"], supabase=sb)
    artifact = _archive(ctx, response.content, mime, kind="video")
    artifact["model"] = data.get("model"); artifact["usage"] = _usage(data.get("usage") or {})
    outputs = {"artifacts": [artifact], "artifact": artifact, "video_url": artifact["url"], "raw": data}
    updated = sb.table("execution_logs").update({"status": "success", "output_json": outputs, "artifacts_json": [artifact], "usage_json": artifact["usage"], "external_ref": {"job_id": str(data["id"]), "provider": "openrouter"}}).eq("id", log["id"]).eq("status", "pending_external").execute().data
    if updated:
        resume_execution(log["execution_id"], _graph_for(sb, log["execution_id"]), get_node_secrets(), int(log["node_id"]), outputs)
    return bool(updated)

class handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        provider = get_query_params(self).get("provider") or urlparse(self.path).path.rsplit("/", 1)[-1]
        length = int(self.headers.get("Content-Length", 0)); raw = self.rfile.read(length)
        if provider == "fal":
            if not _verify_fal(self.headers, raw): send_json(self, 401, {"error": "invalid fal signature"}); return
            event = json.loads(raw); request_id = event.get("request_id")
            if not request_id: send_json(self, 400, {"error": "missing fal request id"}); return
            sb = get_client(); logs = sb.table("execution_logs").select("id,execution_id,node_id").contains("external_ref", {"request_id": request_id}).execute().data
            if not logs: send_json(self, 200, {"ok": True, "duplicate": True}); return
            log = logs[0]; status = "success" if event.get("status") == "OK" else "failed"
            sb.table("execution_logs").update({"status": status, "output_json": event.get("payload", {}), "external_ref": {"request_id": request_id}}).eq("id", log["id"]).execute()
            if status == "success":
                execution = sb.table("executions").select("workflow_id,graph_snapshot").eq("id", log["execution_id"]).single().execute().data
                graph = execution.get("graph_snapshot")
                if not graph:
                    graph = sb.table("workflows").select("graph_json").eq("id", execution["workflow_id"]).single().execute().data["graph_json"]
                resume_execution(log["execution_id"], graph, get_node_secrets(), int(log["node_id"]), event.get("payload", {}))
            send_json(self, 200, {"ok": True}); return
        if provider != "openrouter": send_json(self, 404, {"error": "unknown provider"}); return
        if not _verify_openrouter(self.headers, raw): send_json(self, 401, {"error": "invalid signature"}); return
        try:
            event = json.loads(raw); data = event.get("data") or event
            job_id = data.get("id")
            if not job_id: send_json(self, 400, {"error": "missing provider job id"}); return
            sb = get_client(); logs = sb.table("execution_logs").select("id,execution_id,node_id,status").contains("external_ref", {"job_id": str(job_id)}).execute().data
            if not logs or logs[0].get("status") != "pending_external": send_json(self, 200, {"ok": True, "duplicate": True}); return
            if data.get("status") == "completed":
                complete_openrouter_video(sb, logs[0], data)
            else:
                error = data.get("error") or f"OpenRouter video {data.get('status', 'failed')}"
                sb.table("execution_logs").update({"status": "failed", "error": error}).eq("id", logs[0]["id"]).eq("status", "pending_external").execute()
                sb.table("executions").update({"status": "failed", "error": error}).eq("id", logs[0]["execution_id"]).execute()
            send_json(self, 200, {"ok": True})
        except Exception as exc: send_json(self, 400, {"error": str(exc)})

_jwks, _jwks_at = [], 0.0
def _verify_fal(headers, body):
    global _jwks, _jwks_at
    request_id, user_id, timestamp, signature = (headers.get(key) for key in ("X-Fal-Webhook-Request-Id", "X-Fal-Webhook-User-Id", "X-Fal-Webhook-Timestamp", "X-Fal-Webhook-Signature"))
    if not all((request_id, user_id, timestamp, signature)):
        return False
    try:
        if abs(time.time() - int(timestamp)) > 300: return False
        if not _jwks or time.time() - _jwks_at >= 86400:
            response = httpx.get("https://rest.fal.ai/.well-known/jwks.json", timeout=10); response.raise_for_status(); _jwks, _jwks_at = response.json().get("keys", []), time.time()
        message = "\n".join((request_id, user_id, timestamp, hashlib.sha256(body).hexdigest())).encode()
        signature_bytes = bytes.fromhex(signature)
        for key in _jwks:
            try:
                encoded = key.get("x", ""); public = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)); Ed25519PublicKey.from_public_bytes(public).verify(signature_bytes, message); return True
            except (ValueError, InvalidSignature): pass
    except (ValueError, httpx.HTTPError): pass
    return False


def _verify_openrouter(headers, body):
    secret, header = os.environ.get("OPENROUTER_WEBHOOK_SECRET", ""), headers.get("X-OpenRouter-Signature", "")
    try:
        values = dict(part.split("=", 1) for part in header.split(",") if "=" in part)
        timestamp, supplied = values.get("t"), values.get("v1")
        if not secret or not timestamp or not supplied or abs(time.time() - int(timestamp)) > 300:
            return False
        expected = hmac.new(secret.encode(), timestamp.encode() + b"," + body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, supplied)
    except (TypeError, ValueError):
        return False
