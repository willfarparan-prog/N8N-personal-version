"""
Safety-net executor for `trigger/schedule` nodes. Real cron scheduling happens
in api/cron/poll_schedules.py; the engine seeds this node's outputs from the
scheduled run payload and never calls this runner. This only fires if the
trigger is reached mid-graph, in which case it just passes resolved inputs
through. `config["cron_expression"]` is unused here.
"""
from .base import ExecutionContext, NodeResult, register_node


@register_node("trigger/schedule")
def run(ctx: ExecutionContext) -> NodeResult:
    return NodeResult(status="success", outputs=ctx.inputs)
