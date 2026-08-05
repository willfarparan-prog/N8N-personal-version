"""
Generic HTTP request node for workflow automation.
Uses httpx to make outbound HTTP requests.
"""
from typing import Any

import httpx

from api._lib.nodes.base import ExecutionContext, NodeResult, register_node


@register_node("action/http_request")
def run(ctx: ExecutionContext) -> NodeResult:
    """Execute an HTTP request based on config and inputs."""
    # Resolve URL: inputs take precedence over config
    url: str | None = None
    if "url" in ctx.inputs:
        url = str(ctx.inputs["url"])
    elif "url" in ctx.config:
        url = str(ctx.config["url"])

    if not url:
        return NodeResult(status="failed", error="http_request: no url provided")

    # Resolve method
    method: str = str(ctx.config.get("method", "GET")).upper()

    # Resolve headers
    headers: dict[str, str] = {}
    if "headers" in ctx.config:
        headers = {str(k): str(v) for k, v in ctx.config["headers"].items()}

    # Resolve body: inputs take precedence over config
    body: dict[str, Any] | str | None = None
    if "body" in ctx.inputs:
        body = ctx.inputs["body"]
    elif "body" in ctx.config:
        body = ctx.config["body"]

    # Prepare request arguments
    request_kwargs: dict[str, Any] = {
        "method": method,
        "url": url,
        "headers": headers,
        "timeout": float(ctx.config.get("timeout_seconds", 20)),
    }

    # Handle body - convert dict to JSON, otherwise send as raw content
    if body is not None:
        if isinstance(body, dict):
            request_kwargs["json"] = body
        else:
            request_kwargs["content"] = str(body)

    try:
        resp = httpx.request(**request_kwargs)
    except httpx.HTTPError as exc:
        return NodeResult(status="failed", error=str(exc))
    except Exception as exc:
        return NodeResult(status="failed", error=str(exc))

    content_type = resp.headers.get("content-type", "")
    response_body: Any
    if "application/json" in content_type:
        try:
            response_body = resp.json()
        except Exception:
            response_body = resp.text
    else:
        response_body = resp.text

    return NodeResult(
        status="success",
        outputs={
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
            "body": response_body,
        },
    )
