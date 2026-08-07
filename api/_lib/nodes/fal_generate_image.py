"""Synchronous image generation via fal.ai.
Blocks until the model returns the generated image.
Contrast with fal_train_lora.py's async queued pattern for long-running tasks."""

import json
from typing import Any
import httpx
from api._lib.nodes.base import register_node, ExecutionContext, NodeResult


@register_node("action/fal_generate_image")
def run(ctx: ExecutionContext) -> NodeResult:
    # Validate secrets and config
    fal_key: str | None = ctx.secrets.get("FAL_KEY")
    if not fal_key:
        return NodeResult(
            status="failed",
            error="Missing FAL_KEY in secrets"
        )

    model: str | None = ctx.config.get("model")
    if not model:
        return NodeResult(
            status="failed",
            error="Missing 'model' in config"
        )

    # LoRA resolution logic
    lora_id: str | None = ctx.config.get("lora_id")
    lora_url: str | None = ctx.config.get("lora_url")
    lora_scale: float = ctx.config.get("lora_scale", 1.0)
    trigger_word: str | None = ctx.config.get("trigger_word")
    resolved_lora_url: str | None = lora_url
    resolved_trigger_word: str | None = trigger_word

    if lora_id:
        try:
            result = ctx.supabase.table("trained_loras").select("*").eq("id", lora_id).single().execute()
            row = result.data
            if row["status"] != "ready":
                return NodeResult(
                    status="failed",
                    error=f"LoRA model '{row.get('name', lora_id)}' is not ready (status: {row['status']})"
                )
            resolved_lora_url = row["weights_url"]
            if resolved_trigger_word is None:
                resolved_trigger_word = row.get("trigger_word") or None
        except Exception as exc:
            return NodeResult(
                status="failed",
                error=f"Could not resolve lora_id '{lora_id}': {exc}"
            )
        if not resolved_lora_url:
            return NodeResult(
                status="failed",
                error=f"LoRA model '{lora_id}' has no weights_url despite ready status"
            )

    # Prepare input payload
    input_config: dict[str, Any] = ctx.config.get("input", {})
    # Work on a copy to avoid mutating ctx.config
    payload: dict[str, Any] = input_config.copy()

    # Override prompt from upstream input if present
    if "prompt" in ctx.inputs:
        payload["prompt"] = ctx.inputs["prompt"]

    if resolved_lora_url:
        payload["loras"] = [{"path": resolved_lora_url, "scale": lora_scale}]
        if resolved_trigger_word and payload.get("prompt"):
            prompt = payload["prompt"]
            if resolved_trigger_word.lower() not in prompt.lower():
                payload["prompt"] = f"{resolved_trigger_word}, {prompt}"

    if resolved_lora_url and model == "fal-ai/flux/dev":
        model = "fal-ai/flux-lora"

    # Make request
    url: str = f"https://fal.run/{model}"
    headers: dict[str, str] = {
        "Authorization": f"Key {fal_key}",
        "Content-Type": "application/json"
    }

    try:
        resp: httpx.Response = httpx.post(
            url,
            headers=headers,
            json=payload,
            timeout=120.0
        )

        if 200 <= resp.status_code < 300:
            try:
                result_json: dict[str, Any] = resp.json()
            except (json.JSONDecodeError, ValueError) as json_err:
                return NodeResult(
                    status="failed",
                    error=f"Invalid JSON response: {json_err}"
                )

            # Best-effort image URL extraction
            image_url: str | None = None
            try:
                images: list[dict[str, Any]] = result_json.get("images", [])
                if images:
                    image_url = images[0].get("url")
            except (IndexError, AttributeError, KeyError):
                pass  # Keep image_url as None

            return NodeResult(
                status="success",
                outputs={
                    "result": result_json,
                    "image_url": image_url
                }
            )
        else:
            error_text: str = resp.text[:500] if resp.text else ""
            return NodeResult(
                status="failed",
                error=f"fal.ai returned {resp.status_code}: {error_text}"
            )

    except httpx.HTTPError as http_err:
        return NodeResult(
            status="failed",
            error=str(http_err)
        )
    except Exception as exc:
        return NodeResult(
            status="failed",
            error=str(exc)
        )
