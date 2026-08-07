"""Capability-family OpenRouter image and asynchronous video executors."""
import base64
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from api._lib.nodes.base import Artifact, ExecutionContext, NodeResult, register_node


def _usage(raw: dict[str, Any]) -> dict[str, Any]:
    return {"input_units": raw.get("prompt_tokens", 0), "output_units": raw.get("completion_tokens", 0), "cost_usd": raw.get("cost", 0)}


def _references(value: Any) -> list[dict[str, Any]]:
    """Translate canonical artifacts into OpenRouter's image URL content parts."""
    items = value if isinstance(value, list) else [value] if value else []
    return [
        {"type": "image_url", "image_url": {"url": item["url"]}}
        for item in items if isinstance(item, dict) and item.get("url")
    ]


def _archive(ctx: ExecutionContext, raw: bytes, mime_type: str, *, kind: str) -> dict[str, Any]:
    if len(raw) > 25 * 1024 * 1024:
        raise ValueError("generated asset exceeds the 25 MB storage limit")
    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "video/mp4": "mp4", "video/webm": "webm"}.get(mime_type, "bin")
    path = f"generated/{ctx.execution_id}/{ctx.node_id}/{datetime.now(timezone.utc).timestamp():.6f}.{extension}"
    ctx.supabase.storage.from_("flowforge-assets").upload(path, raw, {"content-type": mime_type, "upsert": "false"})
    row = ctx.supabase.table("generated_assets").insert({
        "execution_id": ctx.execution_id, "storage_path": path, "mime_type": mime_type,
        "size_bytes": len(raw), "metadata_json": {"source": "openrouter", "kind": kind},
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(), "is_persistent": False,
    }).execute().data[0]
    signed = ctx.supabase.storage.from_("flowforge-assets").create_signed_url(path, 3600)
    return Artifact(kind=kind, url=signed.get("signedURL") or signed.get("signedUrl"), mime_type=mime_type,
                    provider="openrouter", metadata={"asset_id": row["id"], "storage_path": path}).to_dict()


def _prompt(ctx: ExecutionContext) -> str:
    prompt = ctx.inputs.get("prompt", ctx.config.get("prompt", ctx.config.get("user_prompt")))
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("OpenRouter media node requires a prompt")
    return prompt.strip()


@register_node("action/openrouter_image")
def run_image(ctx: ExecutionContext) -> NodeResult:
    key, model = ctx.secrets.get("OPENROUTER_API_KEY"), ctx.config.get("model")
    if not key or not model:
        return NodeResult(status="failed", error="OpenRouter Image requires OPENROUTER_API_KEY and a model")
    try:
        payload = {"model": model, "prompt": _prompt(ctx)}
        for name in ("n", "resolution", "aspect_ratio", "size", "quality", "output_format", "background", "output_compression", "seed", "provider"):
            if ctx.config.get(name) not in (None, "", {}): payload[name] = ctx.config[name]
        references = _references(ctx.inputs.get("artifacts") or ctx.inputs.get("reference_artifacts"))
        if references: payload["input_references"] = references
        response = httpx.post("https://openrouter.ai/api/v1/images", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=payload, timeout=120)
        response.raise_for_status(); result = response.json(); usage = _usage(result.get("usage") or {})
        artifacts = []
        for image in result.get("data", []):
            encoded = image.get("b64_json")
            if encoded:
                artifacts.append(_archive(ctx, base64.b64decode(encoded), image.get("media_type") or "image/png", kind="image"))
        if not artifacts: return NodeResult(status="failed", error="OpenRouter Image returned no image data")
        for artifact in artifacts: artifact["model"] = result.get("model", model); artifact["usage"] = usage
        return NodeResult(status="success", outputs={"artifacts": artifacts, "artifact": artifacts[0], "image_url": artifacts[0]["url"], "raw": result}, artifacts=artifacts, usage=usage)
    except (ValueError, httpx.HTTPError) as exc:
        return NodeResult(status="failed", error=f"OpenRouter Image failed: {exc}")


@register_node("action/openrouter_video")
def run_video(ctx: ExecutionContext) -> NodeResult:
    key, model = ctx.secrets.get("OPENROUTER_API_KEY"), ctx.config.get("model")
    if not key or not model:
        return NodeResult(status="failed", error="OpenRouter Video requires OPENROUTER_API_KEY and a model")
    try:
        payload = {"model": model, "prompt": _prompt(ctx)}
        for name in ("duration", "resolution", "aspect_ratio", "size", "generate_audio", "seed", "provider"):
            if ctx.config.get(name) not in (None, "", {}): payload[name] = ctx.config[name]
        refs = _references(ctx.inputs.get("artifacts") or ctx.inputs.get("reference_artifacts"))
        if refs: payload["input_references"] = refs
        first, last = ctx.inputs.get("first_frame"), ctx.inputs.get("last_frame")
        frames = []
        for frame, frame_type in ((first, "first_frame"), (last, "last_frame")):
            if isinstance(frame, dict) and frame.get("url"):
                frames.append({"type": "image_url", "image_url": {"url": frame["url"]}, "frame_type": frame_type})
        if frames: payload["frame_images"] = frames
        base_url = os.environ.get("FLOWFORGE_PUBLIC_BASE_URL", "https://flowforge-pi.vercel.app").rstrip("/")
        payload["callback_url"] = f"{base_url}/api/provider-events/openrouter"
        response = httpx.post("https://openrouter.ai/api/v1/videos", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=payload, timeout=30)
        if response.status_code != 202: response.raise_for_status()
        result = response.json(); job_id = result.get("id")
        if not job_id: return NodeResult(status="failed", error="OpenRouter Video response omitted job id")
        return NodeResult(status="waiting_provider", external_ref={"provider": "openrouter", "job_id": str(job_id), "polling_url": result.get("polling_url"), "model": model})
    except (ValueError, httpx.HTTPError) as exc:
        return NodeResult(status="failed", error=f"OpenRouter Video submission failed: {exc}")
