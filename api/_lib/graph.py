"""Pure LiteGraph traversal helpers, kept independent from providers and Supabase."""


class GraphValidationError(ValueError):
    """Raised before execution when a workflow graph cannot be run safely."""


def build_graph_index(graph_json: dict):
    nodes_by_id = {n["id"]: n for n in graph_json.get("nodes", [])}
    incoming: dict[int, list[tuple[int, int, int]]] = {nid: [] for nid in nodes_by_id}
    for link in graph_json.get("links", []):
        _link_id, origin_id, origin_slot, target_id, target_slot, _type = link
        if origin_id not in nodes_by_id or target_id not in nodes_by_id:
            raise GraphValidationError("Workflow link references a missing node.")
        incoming.setdefault(target_id, []).append((origin_id, origin_slot, target_slot))
    return nodes_by_id, incoming


def topo_order(nodes_by_id: dict, incoming: dict, start_id: int) -> list[int]:
    """Return a deterministic topological order for the trigger's reachable DAG."""
    if start_id not in nodes_by_id:
        raise GraphValidationError(f"Start node {start_id} does not exist.")
    outgoing: dict[int, list[int]] = {nid: [] for nid in nodes_by_id}
    for target_id, edges in incoming.items():
        for origin_id, _os, _ts in edges:
            outgoing.setdefault(origin_id, []).append(target_id)

    reachable: set[int] = set()
    pending = [start_id]
    while pending:
        nid = pending.pop()
        if nid in reachable:
            continue
        reachable.add(nid)
        pending.extend(outgoing.get(nid, []))

    indegree = {
        nid: sum(1 for origin, _os, _ts in incoming.get(nid, []) if origin in reachable)
        for nid in reachable
    }
    ready = sorted(nid for nid, count in indegree.items() if count == 0)
    order: list[int] = []
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for next_id in sorted(outgoing.get(nid, [])):
            if next_id not in indegree:
                continue
            indegree[next_id] -= 1
            if indegree[next_id] == 0:
                ready.append(next_id)
                ready.sort()
    if len(order) != len(reachable):
        raise GraphValidationError("Workflow contains a reachable cycle.")
    return order
