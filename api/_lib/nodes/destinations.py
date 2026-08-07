"""V2 destination nodes consuming the provider-neutral artifact envelope."""
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone, timedelta

import httpx

from api._lib.nodes.base import Artifact, ExecutionContext, NodeResult, register_node
from api._lib.url_safety import is_safe_public_https_url


def _artifacts(ctx):
    value = ctx.inputs.get("artifacts", ctx.inputs.get("artifact", []))
    return value if isinstance(value, list) else ([value] if value else [])


@register_node("destination/capsule_result")
def capsule_result(ctx: ExecutionContext) -> NodeResult:
    """Terminal UI result; the public renderer only consumes this normalized output."""
    artifacts = _artifacts(ctx)
    payload = ctx.inputs.get("payload", ctx.inputs.get("json"))
    text = ctx.inputs.get("text")
    return NodeResult(status="success", outputs={"artifacts": artifacts, "text": text, "payload": payload}, artifacts=artifacts)


@register_node("destination/webhook")
def webhook(ctx: ExecutionContext) -> NodeResult:
    url = ctx.config.get("url") or ctx.inputs.get("url")
    secret = ctx.secrets.get("DESTINATION_WEBHOOK_SIGNING_SECRET")
    if not url or not secret or not is_safe_public_https_url(str(url)):
        return NodeResult(status="failed", error="Webhook destination requires a safe HTTPS URL and signing secret")
    delivery = {"execution_id": ctx.execution_id, "node_id": ctx.node_id, "artifacts": _artifacts(ctx), "payload": ctx.inputs.get("payload", ctx.inputs.get("json")), "text": ctx.inputs.get("text")}
    raw = json.dumps(delivery, separators=(",", ":"), default=str).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw, hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "X-FlowForge-Timestamp": timestamp, "X-FlowForge-Signature": f"sha256={signature}", "Idempotency-Key": f"{ctx.execution_id}:{ctx.node_id}"}
    error = None
    for delay in (0, 5, 30):
        if delay: time.sleep(delay)
        try:
            response = httpx.post(url, content=raw, headers=headers, timeout=15, follow_redirects=False)
            if 200 <= response.status_code < 300:
                return NodeResult(status="success", outputs={"status_code": response.status_code, "response": response.text[:1000]})
            error = f"Webhook returned {response.status_code}: {response.text[:500]}"
            if response.status_code < 500 and response.status_code != 429: break
        except httpx.HTTPError as exc:
            error = str(exc)
    return NodeResult(status="failed", error=error or "Webhook delivery failed")


@register_node("destination/storage")
def storage(ctx: ExecutionContext) -> NodeResult:
    """Persist URL-based artifacts in Flow Forge private storage for manual deletion."""
    persisted = []
    for index, artifact in enumerate(_artifacts(ctx)):
        if not isinstance(artifact, dict) or not artifact.get("url"): continue
        response = httpx.get(artifact["url"], timeout=30, follow_redirects=False)
        response.raise_for_status()
        if len(response.content) > 25 * 1024 * 1024:
            return NodeResult(status="failed", error="Storage destination asset exceeds 25 MB")
        mime_type = response.headers.get("content-type", artifact.get("mime_type", "application/octet-stream")).split(";", 1)[0]
        path = f"persistent/{ctx.execution_id}/{ctx.node_id}-{index}"
        ctx.supabase.storage.from_("flowforge-assets").upload(path, response.content, {"content-type": mime_type, "upsert": "false"})
        created = ctx.supabase.table("generated_assets").insert({"execution_id": ctx.execution_id, "storage_path": path, "mime_type": mime_type, "size_bytes": len(response.content), "metadata_json": artifact.get("metadata", {}), "is_persistent": True}).execute().data[0]
        persisted.append(Artifact(kind=artifact.get("kind", "file"), url=f"/api/assets/{created['id']}", mime_type=mime_type, name=artifact.get("name"), provider="flowforge", metadata={"asset_id": created["id"]}).to_dict())
    return NodeResult(status="success", outputs={"artifacts": persisted}, artifacts=persisted)
