"""
Safety-net executor for `trigger/manual` nodes. The engine normally seeds this
node's outputs directly from the manual run payload and never calls this
runner; this only fires if the trigger is reached mid-graph, in which case it
just passes resolved inputs straight through.
"""
from .base import ExecutionContext, NodeResult, register_node


@register_node("trigger/manual")
def run(ctx: ExecutionContext) -> NodeResult:
    return NodeResult(status="success", outputs=ctx.inputs)
