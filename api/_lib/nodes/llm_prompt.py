import httpx
from api._lib.nodes.base import register_node, ExecutionContext, NodeResult


@register_node("action/llm_prompt")
def run(ctx: ExecutionContext) -> NodeResult:
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

    payload = {
        "model": model,
        "messages": messages
    }

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
            content = response_json["choices"][0]["message"]["content"]
            return NodeResult(
                status="success",
                outputs={
                    "text": content,
                    "raw": response_json
                }
            )
        return NodeResult(
            status="failed",
            error=f"OpenRouter returned {resp.status_code}: {resp.text[:500]}"
        )
    except Exception as exc:
        return NodeResult(status="failed", error=str(exc))
