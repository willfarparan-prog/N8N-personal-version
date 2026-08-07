"""
Shared contract every node executor implements. Do not add per-node special cases
to engine.py — a new node type is always just a new module here plus a registry entry.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Optional

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
class Artifact:
    """Provider-neutral output passed between creative and destination nodes."""

    VALID_KINDS: ClassVar[frozenset[str]] = frozenset(
        {"text", "image", "video", "audio", "file", "json"}
    )

    kind: str
    url: Optional[str] = None
    value: Any = None
    mime_type: Optional[str] = None
    name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in self.VALID_KINDS:
            raise ValueError(f"Unsupported artifact kind: {self.kind}")

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical, JSON-serializable artifact envelope."""
        return {
            "kind": self.kind,
            "url": self.url,
            "value": self.value,
            "mime_type": self.mime_type,
            "name": self.name,
            "provider": self.provider,
            "model": self.model,
            "metadata": self.metadata,
            "usage": self.usage,
        }


@dataclass
class NodeResult:
    status: str  # "success" | "failed" | "waiting_provider"
    outputs: dict[str, Any] = field(default_factory=dict)  # keyed by output slot name, feeds downstream nodes
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    # For status == "waiting_provider": opaque data cron/poll_jobs.py needs to check the job later
    # and resume execution, e.g. {"provider": "fal", "request_id": "...", "poll_url": "..."}.
    external_ref: Optional[dict[str, Any]] = None

    def __post_init__(self) -> None:
        """Accept the pre-V2 async status while executors migrate incrementally."""
        if self.status == "pending_external":
            self.status = "waiting_provider"
