"""
logic/condition — v1 note: this engine does not support conditional graph
branching (i.e. following only a "true" or "false" edge out of this node).
This node only computes and outputs a boolean value under outputs["result"];
how a workflow author uses that value downstream (e.g. an http_request
node's config referencing {{result}}) is outside this node's concern.
"""
from typing import Any
from api._lib.nodes.base import register_node, ExecutionContext, NodeResult


def _resolve(value: Any, inputs: dict[str, Any]) -> Any:
    """Resolve {{input_key}} references against ctx.inputs; else pass through."""
    if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
        key = value[2:-2].strip()
        return inputs.get(key)
    return value


@register_node("logic/condition")
def run(ctx: ExecutionContext) -> NodeResult:
    operator = ctx.config.get("operator")
    valid_ops = ("eq", "neq", "gt", "lt", "gte", "lte", "contains")
    if operator not in valid_ops:
        return NodeResult(
            status="failed",
            error=f"condition: unknown operator '{operator}' (expected one of {valid_ops})"
        )

    left = _resolve(ctx.config.get("left"), ctx.inputs)
    right = _resolve(ctx.config.get("right"), ctx.inputs)

    try:
        if operator == "eq":
            result = left == right
        elif operator == "neq":
            result = left != right
        elif operator == "gt":
            result = left > right
        elif operator == "lt":
            result = left < right
        elif operator == "gte":
            result = left >= right
        elif operator == "lte":
            result = left <= right
        else:  # contains
            result = right in left
    except Exception as exc:
        return NodeResult(
            status="failed",
            error=f"condition: could not evaluate '{operator}' on given operands: {exc}"
        )

    return NodeResult(status="success", outputs={"result": bool(result)})
