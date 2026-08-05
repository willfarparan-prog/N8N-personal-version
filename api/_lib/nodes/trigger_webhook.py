"""
Safety-net executor for `trigger/webhook` nodes. Real webhook payload capture
happens in api/webhook/[id].py; the engine seeds this node's outputs from
that payload and never calls this runner. This only fires if the trigger is
reached mid-graph, in which case it just passes resolved inputs through.
"""
from .base import ExecutionContext, NodeResult, register_node


@register_node("trigger/webhook")
def run(ctx: ExecutionContext) -> NodeResult:
    return NodeResult(status="success", outputs=ctx.inputs)
