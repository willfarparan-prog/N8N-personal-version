"""
This serverless function is triggered every minute by Supabase's pg_cron + pg_net
extensions via HTTP POST. The request includes a shared secret header (X-Cron-Secret)
instead of a session cookie, as there's no browser session for a DB-originated call.
We use this approach because Vercel's free-tier Cron Jobs only run once a day,
which is too coarse for firing schedule-triggered workflows.
"""
import http.server
from datetime import datetime, timezone
from typing import List, Dict, Any

from croniter import croniter
from supabase import Client

from api._lib.auth import check_cron_secret
from api._lib.http_helpers import send_json
from api._lib.supabase_client import get_client
from api._lib.engine import run_execution
from api._lib.secrets import get_node_secrets


class handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        # 1. Validate cron secret
        if not check_cron_secret(self):
            send_json(self, 401, {"error": "invalid cron secret"})
            return

        try:
            client: Client = get_client()
            workflows_resp = (
                client.table("workflows")
                .select("*")
                .eq("is_active", True)
                .execute()
            )
            workflows: List[Dict[str, Any]] = workflows_resp.data

            checked = 0
            fired = 0
            errors: List[Dict[str, str]] = []

            for workflow in workflows:
                graph = workflow.get("graph_json", {})
                nodes = graph.get("nodes", [])

                # Find schedule trigger node
                trigger_node = None
                for node in nodes:
                    if node.get("type") == "trigger/schedule":
                        trigger_node = node
                        break

                if trigger_node is None:
                    continue

                cron_expression = trigger_node.get("properties", {}).get(
                    "cron_expression"
                )
                if not cron_expression:
                    continue

                checked += 1

                # Determine if workflow is due
                last_run = workflow.get("last_scheduled_run_at")
                is_due = False
                if not last_run:
                    is_due = True
                else:
                    # Handle ISO string parsing with potential trailing Z
                    if last_run.endswith("Z"):
                        last_run = last_run.replace("Z", "+00:00")
                    try:
                        last_run_dt = datetime.fromisoformat(last_run)
                        # Ensure last_run_dt is offset-aware (UTC)
                        if last_run_dt.tzinfo is None:
                            last_run_dt = last_run_dt.replace(tzinfo=timezone.utc)
                        next_fire = croniter(
                            cron_expression, last_run_dt
                        ).get_next(datetime)
                        now = datetime.now(timezone.utc)
                        is_due = now >= next_fire
                    except Exception as exc:
                        errors.append(
                            {
                                "workflow_id": workflow["id"],
                                "error": f"Cron parsing failed: {str(exc)}",
                            }
                        )
                        continue

                if is_due:
                    try:
                        # Create execution
                        execution_resp = (
                            client.table("executions")
                            .insert(
                                {
                                    "workflow_id": workflow["id"],
                                    "status": "pending",
                                    "trigger_type": "schedule",
                                    "input_json": {},
                                }
                            )
                            .execute()
                        )
                        execution_id = execution_resp.data[0]["id"]

                        # Seed outputs with empty dict for trigger node
                        seed_outputs = {trigger_node["id"]: {}}
                        run_execution(
                            execution_id=execution_id,
                            workflow_graph=graph,
                            secrets=get_node_secrets(),
                            seed_outputs=seed_outputs,
                        )

                        # Update last scheduled run timestamp
                        now_iso = datetime.now(timezone.utc).isoformat()
                        (
                            client.table("workflows")
                            .update({"last_scheduled_run_at": now_iso})
                            .eq("id", workflow["id"])
                            .execute()
                        )

                        fired += 1
                    except Exception as exc:
                        errors.append(
                            {
                                "workflow_id": workflow["id"],
                                "error": str(exc),
                            }
                        )

            send_json(
                self,
                200,
                {"checked": checked, "fired": fired, "errors": errors},
            )
        except Exception as exc:
            send_json(
                self,
                500,
                {"error": f"Server error: {str(exc)}"},
            )
