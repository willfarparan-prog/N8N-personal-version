import json
import httpx
from api._lib.nodes.base import Artifact, register_node, ExecutionContext, NodeResult


def _run_text(ctx: ExecutionContext) -> NodeResult:
    """Generate text via OpenRouter's chat completions API."""
    # 1. resolve prompt (inputs["prompt"] takes precedence over config.user_prompt)
    prompt = None
    if "prompt" in ctx.inputs:
        prompt = ctx.inputs["prompt"]
    elif "user_prompt" in ctx.config:
        prompt = ctx.config["user_prompt"]

    if not prompt:
        return NodeResult(
            status="failed",
            error="llm_prompt: No prompt provided in config.user_prompt nor inputs.prompt"
        )

    # 2. check API key
    api_key = ctx.secrets.get("OPENROUTER_API_KEY")
    if not api_key:
        return NodeResult(
            status="failed",
            error="llm_prompt: Missing OPENROUTER_API_KEY in secrets"
        )

    # 3. prepare request
    model = ctx.config.get("model") or "deepseek/deepseek-v3.2"
    system_prompt = ctx.config.get("system_prompt", "")
    messages = []
    if system_prompt and isinstance(system_prompt, str) and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": str(prompt)})

    payload = {"model": model, "messages": messages}
    if ctx.config.get("temperature") is not None:
        payload["temperature"] = ctx.config["temperature"]
    if ctx.config.get("max_tokens") is not None:
        payload["max_tokens"] = ctx.config["max_tokens"]
    if ctx.config.get("fallback_models"):
        payload.update({"models": ctx.config["fallback_models"], "route": "fallback"})
    response_format = ctx.config.get("response_format")
    if response_format == "json_object":
        payload["response_format"] = {"type": "json_object"}
    elif response_format == "json_schema" and isinstance(ctx.config.get("json_schema"), dict):
        payload["response_format"] = {"type": "json_schema", "json_schema": ctx.config["json_schema"]}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # 4. make request
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                headers=headers
            )

        # 5. handle response
        if 200 <= resp.status_code < 300:
            response_json = resp.json()
            content = response_json["choices"][0]["message"]["content"] or ""
            usage_raw = response_json.get("usage") or {}
            usage = {"input_units": usage_raw.get("prompt_tokens", 0), "output_units": usage_raw.get("completion_tokens", 0), "cost_usd": usage_raw.get("cost", 0)}
            structured = None
            if response_format in ("json_object", "json_schema"):
                try:
                    structured = json.loads(content)
                except ValueError:
                    return NodeResult(status="failed", error="OpenRouter returned invalid structured JSON")
            return NodeResult(
                status="success",
                outputs={
                    "text": content,
                    "json": structured,
                    "raw": response_json
                },
                artifacts=[Artifact(kind="json" if structured is not None else "text", value=structured if structured is not None else content, provider="openrouter", model=response_json.get("model", model), usage=usage).to_dict()],
                usage=usage,
            )
        return NodeResult(
            status="failed",
            error=f"OpenRouter returned {resp.status_code}: {resp.text[:500]}"
        )
    except Exception as exc:
        return NodeResult(status="failed", error=str(exc))


@register_node("action/llm_prompt")
def run_legacy(ctx: ExecutionContext) -> NodeResult:
    """Compatibility alias retained for saved V1 workflows."""
    return _run_text(ctx)


@register_node("action/openrouter_text")
def run_openrouter_text(ctx: ExecutionContext) -> NodeResult:
    """V2 OpenRouter text node."""
    return _run_text(ctx)
