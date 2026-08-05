"""
Shared contract every node executor implements. Do not add per-node special cases
to engine.py — a new node type is always just a new module here plus a registry entry.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

NODE_REGISTRY: dict[str, Callable[["ExecutionContext"], "NodeResult"]] = {}


def register_node(node_type: str):
    """Decorator: @register_node("action/http_request") def run(ctx: ExecutionContext) -> NodeResult: ..."""
    def decorator(fn: Callable[["ExecutionContext"], "NodeResult"]):
        NODE_REGISTRY[node_type] = fn
        return fn
    return decorator


@dataclass
class ExecutionContext:
    execution_id: str
    node_id: str
    config: dict[str, Any]        # this node's `properties` from the LiteGraph JSON
    inputs: dict[str, Any]        # resolved from upstream nodes' outputs, keyed by input slot name
    secrets: dict[str, str]       # read-only: FAL_KEY, OPENROUTER_API_KEY, etc. (from os.environ, never persisted)
    supabase: Any                 # supabase-py client (service role) — see supabase_client.get_client()


@dataclass
class NodeResult:
    status: str  # "success" | "failed" | "pending_external"
    outputs: dict[str, Any] = field(default_factory=dict)  # keyed by output slot name, feeds downstream nodes
    error: Optional[str] = None
    # For status == "pending_external": opaque data cron/poll_jobs.py needs to check the job later
    # and resume execution, e.g. {"provider": "fal", "request_id": "...", "poll_url": "..."}.
    external_ref: Optional[dict[str, Any]] = None
