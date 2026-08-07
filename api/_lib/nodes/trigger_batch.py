"""Safety-net executor for child executions created by the Batch Input trigger."""
from .base import ExecutionContext, NodeResult, register_node


@register_node("trigger/batch_input")
def run(ctx: ExecutionContext) -> NodeResult:
    # Batch rows are seeded by api/batches.py before the DAG starts.  Retaining
    # this executor makes graphs deterministic if the trigger is resumed later.
    return NodeResult(status="success", outputs=ctx.inputs)
