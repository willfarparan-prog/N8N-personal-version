"""
Walks a workflow graph (LiteGraph JSON: {nodes: [...], links: [...]}) and executes it
node by node via NODE_REGISTRY (api._lib.nodes.base). This is the one place that
understands graph traversal — node executors never see the graph, only their own
resolved inputs/config.

Long-running external jobs (e.g. a fal.ai training run) are handled by a node executor
returning NodeResult(status="waiting_provider", external_ref={...}). run_execution then
stops and persists that state; api/cron/poll_jobs.py later resumes the walk via
resume_execution() once the external job finishes. This avoids needing a long-lived
server — everything after the first pending node happens across separate, short
serverless invocations.
"""
from datetime import datetime, timezone
from typing import Any, Optional

from api._lib import nodes  # noqa: F401  (import for its side effect: populates NODE_REGISTRY)
from api._lib.nodes.base import NODE_REGISTRY, ExecutionContext, NodeResult
from api._lib.graph import GraphValidationError, build_graph_index as _build_graph_index, topo_order as _topo_order
from api._lib.supabase_client import get_client

TRIGGER_PREFIX = "trigger/"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_inputs(node: dict, incoming: dict, nodes_by_id: dict, node_outputs: dict[int, dict]) -> dict[str, Any]:
    """
    Map upstream nodes' outputs onto this node's named inputs.

    Primary strategy: match by NAME — the origin node's declared output-slot name
    (from its own `outputs` list in the graph JSON) is looked up directly in that
    node's actual outputs dict. This means an executor's NodeResult.outputs key
    order never has to match the UI's declared output-slot order, only the names
    have to agree — far less fragile than positional binding.

    Fallback: for dynamic-shaped nodes (trigger payloads, set_transform's
    user-defined mappings) where the origin's declared output slots don't name-match
    its actual runtime keys, fall back to positional indexing into the outputs dict
    as a best effort.
    """
    inputs: dict[str, Any] = {}
    input_defs = node.get("inputs") or []
    for origin_id, origin_slot, target_slot in incoming.get(node["id"], []):
        if origin_id not in node_outputs or target_slot >= len(input_defs):
            continue
        input_name = input_defs[target_slot].get("name", f"input_{target_slot}")
        origin_outputs = node_outputs[origin_id]
        origin_node = nodes_by_id.get(origin_id) or {}
        origin_output_defs = origin_node.get("outputs") or []

        if origin_slot < len(origin_output_defs):
            origin_slot_name = origin_output_defs[origin_slot].get("name")
            if origin_slot_name is not None and origin_slot_name in origin_outputs:
                inputs[input_name] = origin_outputs[origin_slot_name]
                continue

        origin_slot_names = list(origin_outputs.keys())
        if origin_slot < len(origin_slot_names):
            inputs[input_name] = origin_outputs[origin_slot_names[origin_slot]]
    return inputs


def run_execution(
    execution_id: str,
    workflow_graph: dict,
    secrets: dict[str, str],
    start_node_id: Optional[int] = None,
    seed_outputs: Optional[dict[int, dict]] = None,
) -> None:
    """Entry point for a fresh run (manual/webhook/schedule trigger). See resume_execution for continuing a pending_external node."""
    sb = get_client()
    nodes_by_id, incoming = _build_graph_index(workflow_graph)

    if start_node_id is None:
        trigger = next((n for n in nodes_by_id.values() if n.get("type", "").startswith(TRIGGER_PREFIX)), None)
        if trigger is None:
            _fail_execution(sb, execution_id, "No trigger node found in workflow graph.")
            return
        start_node_id = trigger["id"]

    try:
        order = _topo_order(nodes_by_id, incoming, start_node_id)
    except GraphValidationError as exc:
        _fail_execution(sb, execution_id, str(exc))
        return
    sb.table("executions").update({"status": "running"}).eq("id", execution_id).execute()
    _walk(sb, execution_id, nodes_by_id, incoming, order, secrets, seed_outputs or {})


def resume_execution(
    execution_id: str,
    workflow_graph: dict,
    secrets: dict[str, str],
    resume_node_id: int,
    resume_outputs: dict[str, Any],
) -> None:
    """
    Called by api/cron/poll_jobs.py once a pending_external node's job has finished.

    Rebuilds node_outputs from the persisted execution_logs (not just resume_node_id's own
    output) so that any downstream node fed directly by an *earlier* node — not only by the
    node that just resumed — still resolves correctly. Then re-enters _walk starting AT
    resume_node_id itself (skipped via skip_ids) so its full forward BFS naturally covers
    every fan-out branch, instead of only the first outgoing edge.
    """
    sb = get_client()
    nodes_by_id, incoming = _build_graph_index(workflow_graph)

    prior_logs = (
        sb.table("execution_logs")
        .select("node_id, output_json")
        .eq("execution_id", execution_id)
        .eq("status", "success")
        .execute()
    )
    node_outputs: dict[int, dict] = {int(row["node_id"]): (row["output_json"] or {}) for row in prior_logs.data}
    node_outputs[resume_node_id] = resume_outputs

    try:
        order = _topo_order(nodes_by_id, incoming, resume_node_id)
    except GraphValidationError as exc:
        _fail_execution(sb, execution_id, str(exc))
        return
    sb.table("executions").update({"status": "running"}).eq("id", execution_id).execute()
    _walk(sb, execution_id, nodes_by_id, incoming, order, secrets, node_outputs, skip_ids={resume_node_id})


def _walk(sb, execution_id, nodes_by_id, incoming, order, secrets, seed_outputs, skip_ids: Optional[set[int]] = None):
    skip_ids = skip_ids or set()
    node_outputs: dict[int, dict] = dict(seed_outputs)
    actual_cost = 0.0

    for nid in order:
        if nid in skip_ids:
            continue
        node = nodes_by_id[nid]
        node_type = node.get("type", "")

        if node_type.startswith(TRIGGER_PREFIX) and nid not in node_outputs:
            node_outputs[nid] = seed_outputs.get(nid, {})
            continue

        runner = NODE_REGISTRY.get(node_type)
        if runner is None:
            _fail_execution(sb, execution_id, f"Unknown node type: {node_type}")
            return

        inputs = _resolve_inputs(node, incoming, nodes_by_id, node_outputs)
        config = node.get("properties", {}) or {}
        log_id = _start_log(sb, execution_id, node, inputs)
        ctx = ExecutionContext(
            execution_id=execution_id, node_id=str(nid), config=config,
            inputs=inputs, secrets=secrets, supabase=sb,
        )

        try:
            result: NodeResult = runner(ctx)
        except Exception as exc:  # node executors should catch their own errors; this is only a safety net
            result = NodeResult(status="failed", error=f"{type(exc).__name__}: {exc}")

        _finish_log(sb, log_id, result)
        try:
            actual_cost += float((result.usage or {}).get("cost_usd") or 0)
        except (TypeError, ValueError):
            pass

        if result.status == "failed":
            _fail_execution(sb, execution_id, result.error or f"Node {nid} failed")
            return

        if result.status == "waiting_provider":
            # Keep the persisted status compatible with the existing polling
            # route until its schema migration introduces waiting_provider.
            sb.table("executions").update({"status": "pending_external"}).eq("id", execution_id).execute()
            sb.table("execution_logs").update({
                "output_json": {"external_ref": result.external_ref},
            }).eq("id", log_id).execute()
            return  # api/cron/poll_jobs.py resumes this later via resume_execution()

        resolved_outputs = dict(result.outputs)
        # Nodes can publish provider-neutral artifacts without every existing
        # LiteGraph definition needing a new output slot immediately.
        if result.artifacts and "artifacts" not in resolved_outputs:
            resolved_outputs["artifacts"] = result.artifacts
        node_outputs[nid] = resolved_outputs

    terminal_ids = [
        nid for nid in order
        if not any(origin == nid and target in order for target, edges in incoming.items() for origin, _os, _ts in edges)
    ]
    terminal_outputs = {str(nid): node_outputs.get(nid, {}) for nid in terminal_ids}
    sb.table("executions").update({
        "status": "success",
        "output_json": (terminal_outputs.get(str(terminal_ids[0]), {}) if len(terminal_ids) == 1 else {"terminal_outputs": terminal_outputs}),
        "actual_cost_usd": actual_cost,
        "finished_at": _now(),
    }).eq("id", execution_id).execute()


def _start_log(sb, execution_id, node, resolved_inputs: dict[str, Any]) -> str:
    row = sb.table("execution_logs").insert({
        "execution_id": execution_id,
        "node_id": str(node["id"]),
        "node_type": node.get("type", ""),
        "status": "running",
        "input_json": resolved_inputs,
    }).execute()
    return row.data[0]["id"]


def _finish_log(sb, log_id, result: NodeResult) -> None:
    sb.table("execution_logs").update({
        # The V2 migration may update the constraint, but deployed V1 logs use
        # pending_external. Keep them readable during the compatibility window.
        "status": "pending_external" if result.status == "waiting_provider" else result.status,
        "output_json": result.outputs,
        "artifacts_json": result.artifacts,
        "usage_json": result.usage,
        "external_ref": result.external_ref,
        "error": result.error,
        "finished_at": _now(),
    }).eq("id", log_id).execute()


def _fail_execution(sb, execution_id, error: str) -> None:
    sb.table("executions").update({
        "status": "failed", "error": error, "finished_at": _now(),
    }).eq("id", execution_id).execute()
