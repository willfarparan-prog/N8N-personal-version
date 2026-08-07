"""Small service-role adapter for Flow Forge's Postgres-backed work queue."""
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "success"
FAILED = "failed"
CANCELED = "canceled"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_job(client: Any, job_type: str, execution_id: str, *, batch_item_id: Optional[str] = None,
                payload: Optional[Mapping[str, Any]] = None, idempotency_key: str,
                max_attempts: int = 3, available_at: Optional[datetime] = None) -> dict[str, Any]:
    """Queue an idempotent unit of work; the database enforces duplicate protection."""
    if not isinstance(payload or {}, Mapping):
        raise ValueError("payload must be an object")
    if not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be between 1 and 3")
    result = client.table("workflow_jobs").insert({
        "job_type": job_type, "execution_id": execution_id, "batch_item_id": batch_item_id,
        "payload_json": dict(payload or {}), "status": QUEUED, "max_attempts": max_attempts,
        "idempotency_key": idempotency_key,
        "available_at": (available_at or _now()).isoformat(),
    }).execute()
    return result.data[0]


def claim_jobs(client: Any, limit: int = 3) -> list[dict[str, Any]]:
    """Atomically lease up to three jobs. Claiming is never done in application code."""
    if not isinstance(limit, int) or not 1 <= limit <= 3:
        raise ValueError("limit must be between 1 and 3")
    result = client.rpc("claim_flowforge_jobs", {"p_limit": limit}).execute()
    return result.data or []


def complete_job(client: Any, job_id: str) -> dict[str, Any]:
    result = client.table("workflow_jobs").update({
        "status": SUCCEEDED, "completed_at": _now().isoformat(), "lease_expires_at": None,
    }).eq("id", job_id).eq("status", RUNNING).execute()
    if not result.data:
        raise RuntimeError("job was not actively leased")
    return result.data[0]


def retry_or_fail_job(client: Any, job: Mapping[str, Any], error: str, retryable: bool) -> dict[str, Any]:
    """Retry only provider-transient failures, twice at five then thirty seconds."""
    attempts, max_attempts = int(job["attempts"]), int(job["max_attempts"])
    update: dict[str, Any] = {"last_error": error[:2000], "lease_expires_at": None}
    if retryable and attempts < max_attempts:
        update.update({"status": QUEUED, "available_at": (_now() + timedelta(seconds=(5 if attempts == 1 else 30))).isoformat()})
    else:
        update.update({"status": FAILED, "completed_at": _now().isoformat()})
    result = client.table("workflow_jobs").update(update).eq("id", job["id"]).eq("status", RUNNING).execute()
    if not result.data:
        raise RuntimeError("job was not actively leased")
    updated = result.data[0]
    if updated["status"] == FAILED and job.get("batch_item_id"):
        client.table("batch_items").update({"status": FAILED, "error": error[:2000], "finished_at": _now().isoformat()}).eq("id", job["batch_item_id"]).execute()
        client.table("executions").update({"status": FAILED, "error": error[:2000], "finished_at": _now().isoformat()}).eq("id", job["execution_id"]).execute()
    return updated


def cancel_job(client: Any, job_id: str) -> Optional[dict[str, Any]]:
    """Cancel only undispatched work; running providers require separate confirmation."""
    result = client.table("workflow_jobs").update({"status": CANCELED, "completed_at": _now().isoformat()}).eq("id", job_id).eq("status", QUEUED).execute()
    return result.data[0] if result.data else None
