"""
Supabase database query node for workflow automation.
Allows workflows to read/write user-defined tables in Supabase (separate
from the engine-managed workflows/executions/execution_logs tables).
"""
from typing import Any

from api._lib.nodes.base import ExecutionContext, NodeResult, register_node


@register_node("action/supabase_query")
def run(ctx: ExecutionContext) -> NodeResult:
    """Execute a Supabase table operation based on config and inputs."""
    config: dict[str, Any] = ctx.config

    table_name = config.get("table")
    if not table_name:
        return NodeResult(status="failed", error="supabase_query: 'table' is required")

    operation = config.get("operation")
    if not operation:
        return NodeResult(status="failed", error="supabase_query: 'operation' is required")

    # Resolve data: inputs take precedence over config
    data: dict[str, Any] | None = None
    if "data" in ctx.inputs:
        data = ctx.inputs["data"]
    elif "data" in config:
        data = config["data"]

    filters: dict[str, Any] = config.get("filters") or {}

    try:
        table = ctx.supabase.table(table_name)

        if operation == "select":
            query = table.select("*")
            for column, value in filters.items():
                query = query.eq(column, value)
            result = query.execute()

        elif operation == "insert":
            if data is None:
                return NodeResult(
                    status="failed",
                    error="supabase_query: 'data' is required for insert",
                )
            result = table.insert(data).execute()

        elif operation == "update":
            if data is None:
                return NodeResult(
                    status="failed",
                    error="supabase_query: 'data' is required for update",
                )
            query = table.update(data)
            for column, value in filters.items():
                query = query.eq(column, value)
            result = query.execute()

        elif operation == "delete":
            query = table.delete()
            for column, value in filters.items():
                query = query.eq(column, value)
            result = query.execute()

        else:
            return NodeResult(
                status="failed",
                error=f"supabase_query: unknown operation {operation!r}",
            )

        return NodeResult(status="success", outputs={"data": result.data})

    except Exception as exc:
        return NodeResult(status="failed", error=str(exc))
