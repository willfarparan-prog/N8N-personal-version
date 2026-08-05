from typing import Any
from api._lib.nodes.base import register_node, ExecutionContext, NodeResult


def _resolve(value: Any, inputs: dict[str, Any]) -> Any:
    """Resolve {{input_key}} references against ctx.inputs; else pass through."""
    if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
        key = value[2:-2].strip()
        return inputs.get(key)
    return value


@register_node("data/set")
def run(ctx: ExecutionContext) -> NodeResult:
    """Simple field remapping/reshaping — deliberately not arbitrary code eval."""
    mappings = ctx.config.get("mappings")
    if not isinstance(mappings, list):
        return NodeResult(
            status="failed",
            error="set_transform: 'mappings' must be a list"
        )

    outputs: dict[str, Any] = {}
    for idx, mapping in enumerate(mappings):
        if not isinstance(mapping, dict):
            return NodeResult(
                status="failed",
                error=f"set_transform: mapping at index {idx} is not an object"
            )
        if "output_name" not in mapping:
            return NodeResult(
                status="failed",
                error=f"set_transform: mapping at index {idx} is missing 'output_name'"
            )
        output_name = mapping["output_name"]
        source = mapping.get("source")
        outputs[output_name] = _resolve(source, ctx.inputs)

    return NodeResult(status="success", outputs=outputs)
