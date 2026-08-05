"""Poll pending external workflow executions to resume them when ready.

This endpoint is called every minute by Supabase's pg_cron + pg_net extensions via
HTTP POST (with a shared secret header instead of a session cookie, since there's
no browser session for a DB-originated call), because Vercel's free-tier Cron Jobs
only run once a day which is too coarse for resuming paused workflow executions
(a fal.ai job still running, or a `delay` node waiting to elapse).
"""

import os
from datetime import datetime, timezone

import httpx
import http.server

from api._lib.auth import check_cron_secret
from api._lib.http_helpers import send_json
from api._lib.supabase_client import get_client
from api._lib.engine import resume_execution
from api._lib.secrets import get_node_secrets


class handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if not check_cron_secret(self):
            send_json(self, 401, {"error": "invalid cron secret"})
            return

        try:
            client = get_client()
            executions_resp = (
                client.table("executions")
                .select("*")
                .eq("status", "pending_external")
                .execute()
            )
            pending_executions = executions_resp.data

            resumed_count = 0
            errors = []

            for execution in pending_executions:
                try:
                    logs_resp = (
                        client.table("execution_logs")
                        .select("*")
                        .eq("execution_id", execution["id"])
                        .order("started_at", desc=True)
                        .execute()
                    )
                    logs = logs_resp.data

                    pending_log = None
                    for log in logs:
                        if log.get("status") == "pending_external":
                            pending_log = log
                            break

                    if not pending_log:
                        continue

                    node_id = int(pending_log["node_id"])
                    external_ref = pending_log["output_json"]["external_ref"]
                    provider = external_ref.get("provider")

                    if provider == "delay":
                        resume_at_str = external_ref["resume_at"]
                        resume_at_iso = resume_at_str.replace("Z", "+00:00")
                        resume_at = datetime.fromisoformat(resume_at_iso)

                        if datetime.now(timezone.utc) >= resume_at:
                            workflow_resp = (
                                client.table("workflows")
                                .select("graph_json")
                                .eq("id", execution["workflow_id"])
                                .single()
                                .execute()
                            )
                            graph_json = workflow_resp.data["graph_json"]

                            resume_execution(
                                execution_id=execution["id"],
                                workflow_graph=graph_json,
                                secrets=get_node_secrets(),
                                resume_node_id=node_id,
                                resume_outputs={},
                            )
                            resumed_count += 1
                        # else: still waiting, skip

                    elif provider == "fal":
                        fal_key = os.environ.get("FAL_KEY", "")
                        status_url = external_ref["status_url"]
                        auth_header = {"Authorization": f"Key {fal_key}"}

                        try:
                            status_resp = httpx.get(
                                status_url, headers=auth_header, timeout=30
                            )
                            status_resp.raise_for_status()
                        except Exception as e:
                            errors.append(
                                {
                                    "execution_id": execution["id"],
                                    "error": f"fal status request failed: {str(e)}",
                                }
                            )
                            continue

                        status_data = status_resp.json()
                        fal_status = status_data.get("status")

                        if fal_status == "COMPLETED":
                            response_url = external_ref["response_url"]
                            try:
                                response_resp = httpx.get(
                                    response_url, headers=auth_header, timeout=30
                                )
                                response_resp.raise_for_status()
                            except Exception as e:
                                errors.append(
                                    {
                                        "execution_id": execution["id"],
                                        "error": f"fal response request failed: {str(e)}",
                                    }
                                )
                                continue

                            result_json = response_resp.json()

                            workflow_resp = (
                                client.table("workflows")
                                .select("graph_json")
                                .eq("id", execution["workflow_id"])
                                .single()
                                .execute()
                            )
                            graph_json = workflow_resp.data["graph_json"]

                            resume_execution(
                                execution_id=execution["id"],
                                workflow_graph=graph_json,
                                secrets=get_node_secrets(),
                                resume_node_id=node_id,
                                resume_outputs=result_json,
                            )
                            resumed_count += 1

                        elif fal_status in ("IN_QUEUE", "IN_PROGRESS"):
                            # still waiting, skip
                            pass
                        else:
                            errors.append(
                                {
                                    "execution_id": execution["id"],
                                    "error": f"unexpected fal status: {fal_status}",
                                }
                            )

                    else:
                        errors.append(
                            {
                                "execution_id": execution["id"],
                                "error": f"unknown external_ref provider: {provider}",
                            }
                        )

                except Exception as e:
                    errors.append(
                        {"execution_id": execution["id"], "error": str(e)}
                    )
                    continue

            send_json(
                self,
                200,
                {
                    "checked": len(pending_executions),
                    "resumed": resumed_count,
                    "errors": errors,
                },
            )

        except Exception as e:
            send_json(
                self, 500, {"error": f"Failed to poll jobs: {str(e)}"}
            )
