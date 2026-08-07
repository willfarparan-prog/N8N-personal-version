"""Schema-driven fal queue node; endpoint controls are supplied by the cached catalog."""
import httpx
import os

from api._lib.nodes.base import ExecutionContext, NodeResult, register_node

@register_node("action/fal_universal_media")
def run(ctx: ExecutionContext) -> NodeResult:
    key = ctx.secrets.get("FAL_KEY")
    endpoint = ctx.config.get("endpoint") or ctx.config.get("model")
    if not key or not endpoint:
        return NodeResult(status="failed", error="fal Universal Media requires FAL_KEY and an endpoint")
    payload = dict(ctx.config.get("input") or {})
    if "prompt" in ctx.inputs: payload["prompt"] = ctx.inputs["prompt"]
    if ctx.inputs.get("artifacts"): payload.setdefault("references", ctx.inputs["artifacts"])
    try:
        base_url = os.environ.get("FLOWFORGE_PUBLIC_BASE_URL", "https://flowforge-pi.vercel.app").rstrip("/")
        response = httpx.post(f"https://queue.fal.run/{endpoint}", params={"fal_webhook": f"{base_url}/api/provider-events/fal"}, headers={"Authorization": f"Key {key}", "Content-Type": "application/json"}, json=payload, timeout=30)
        response.raise_for_status(); queued = response.json()
        request_id = queued.get("request_id")
        if not request_id: return NodeResult(status="failed", error="fal queue response omitted request_id")
        return NodeResult(status="waiting_provider", external_ref={"provider": "fal", "request_id": request_id, "status_url": queued.get("status_url"), "response_url": queued.get("response_url"), "endpoint": endpoint})
    except httpx.HTTPError as exc:
        return NodeResult(status="failed", error=f"fal queue submission failed: {exc}")
