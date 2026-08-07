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
from api._lib.engine import resume_execution, run_execution
from api._lib.secrets import get_node_secrets
from api._lib.job_queue import claim_jobs, complete_job, retry_or_fail_job
from api.provider_events import complete_openrouter_video


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

            # Drain a bounded number of application-owned jobs first. A batch
            # can therefore never monopolize a serverless invocation, and the
            # SQL claim function is the only place a lease is acquired.
            for job in claim_jobs(client, limit=3):
                try:
                    if job["job_type"] != "execute_workflow":
                        raise ValueError(f"unsupported job type: {job['job_type']}")
                    payload = job.get("payload_json") or {}
                    graph = payload.get("graph_snapshot")
                    if not isinstance(graph, dict):
                        raise ValueError("queued workflow job lacks graph snapshot")
                    trigger = next((node for node in graph.get("nodes", []) if node.get("type", "").startswith("trigger/")), None)
                    if trigger is None:
                        raise ValueError("queued workflow has no trigger")
                    run_execution(job["execution_id"], graph, get_node_secrets(), seed_outputs={trigger["id"]: payload.get("input", {})})
                    execution = client.table("executions").select("status,output_json,actual_cost_usd,error").eq("id", job["execution_id"]).single().execute().data
                    if job.get("batch_item_id"):
                        client.table("batch_items").update({
                            "status": execution["status"], "output_json": execution.get("output_json"),
                            "actual_cost_usd": execution.get("actual_cost_usd", 0), "error": execution.get("error"),
                            "finished_at": _now() if execution["status"] in ("success", "failed", "canceled") else None,
                        }).eq("id", job["batch_item_id"]).execute()
                    complete_job(client, job["id"])
                except Exception as exc:
                    # Request validation and graph defects do not retry; normal
                    # provider/network failures get the two queue retries.
                    retryable = not isinstance(exc, ValueError)
                    retry_or_fail_job(client, job, str(exc), retryable=retryable)
                    errors.append({"job_id": job["id"], "error": str(exc)})

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
                                # Delay has no output of its own — replay whatever fed
                                # into it so downstream nodes still receive their data.
                                resume_outputs=external_ref.get("passthrough") or {},
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

                            trained_lora_id = external_ref.get("trained_lora_id")
                            if trained_lora_id:
                                weights_url = result_json.get("diffusers_lora_file", {}).get("url") or result_json.get("lora_file", {}).get("url")
                                try:
                                    client.table("trained_loras").update({"status": "ready", "weights_url": weights_url, "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", trained_lora_id).execute()
                                except Exception as exc:
                                    errors.append({"execution_id": execution["id"], "error": f"failed to update trained_loras: {exc}"})

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
                            trained_lora_id = external_ref.get("trained_lora_id")
                            if trained_lora_id:
                                try:
                                    client.table("trained_loras").update({"status": "failed", "error": f"unexpected fal status: {fal_status}", "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", trained_lora_id).execute()
                                except Exception:
                                    pass
                            errors.append(
                                {
                                    "execution_id": execution["id"],
                                    "error": f"unexpected fal status: {fal_status}",
                                }
                            )

                    elif provider == "openrouter":
                        key, poll_url = os.environ.get("OPENROUTER_API_KEY", ""), external_ref.get("polling_url")
                        if not key or not poll_url:
                            errors.append({"execution_id": execution["id"], "error": "OpenRouter video has no polling URL or API key"}); continue
                        response = httpx.get(poll_url, headers={"Authorization": f"Bearer {key}"}, timeout=30)
                        response.raise_for_status(); data = response.json(); status = data.get("status")
                        if status == "completed":
                            complete_openrouter_video(client, pending_log, data); resumed_count += 1
                        elif status in ("pending", "in_progress"):
                            pass
                        else:
                            error = data.get("error") or f"OpenRouter video {status or 'failed'}"
                            client.table("execution_logs").update({"status": "failed", "error": error}).eq("id", pending_log["id"]).execute()
                            client.table("executions").update({"status": "failed", "error": error}).eq("id", execution["id"]).execute()

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
