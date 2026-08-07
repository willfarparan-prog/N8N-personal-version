"""Async LoRA training via fal.ai queued pattern.
Always returns pending_external on successful submission — a separate poller will
check job status later. Contrast with fal_generate_image.py's synchronous pattern."""

import json
from typing import Any
import httpx
from api._lib.nodes.base import register_node, ExecutionContext, NodeResult


@register_node("action/fal_train_lora")
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

    name: str | None = ctx.config.get("name")
    if not name:
        return NodeResult(
            status="failed",
            error="Missing 'name' in config"
        )

    # Prepare input payload
    payload: dict[str, Any] = ctx.config.get("input", {})

    # Make request to queue endpoint
    url: str = f"https://queue.fal.run/{model}"
    headers: dict[str, str] = {
        "Authorization": f"Key {fal_key}",
        "Content-Type": "application/json"
    }

    try:
        resp: httpx.Response = httpx.post(
            url,
            headers=headers,
            json=payload,
            timeout=30.0
        )

        if 200 <= resp.status_code < 300:
            try:
                result_json: dict[str, Any] = resp.json()
            except (json.JSONDecodeError, ValueError) as json_err:
                return NodeResult(
                    status="failed",
                    error=f"Invalid JSON response: {json_err}"
                )

            trained_lora_id = None
            try:
                insert_result = ctx.supabase.table("trained_loras").insert({
                    "name": name,
                    "trigger_word": payload.get("trigger_word", ""),
                    "status": "training",
                    "source_execution_id": ctx.execution_id,
                    "training_input": payload
                }).execute()
                trained_lora_id = insert_result.data[0]["id"]
            except Exception:
                # Proceed even if DB insert fails; the fal job was already
                # submitted successfully and shouldn't be abandoned.
                pass

            return NodeResult(
                status="pending_external",
                external_ref={
                    "provider": "fal",
                    "model": model,
                    "request_id": result_json.get("request_id"),
                    "status_url": result_json.get("status_url"),
                    "response_url": result_json.get("response_url"),
                    "trained_lora_id": trained_lora_id,
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
