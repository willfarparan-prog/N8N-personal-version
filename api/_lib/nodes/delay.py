from datetime import datetime, timezone, timedelta
from api._lib.nodes.base import register_node, ExecutionContext, NodeResult


@register_node("action/delay")
def run(ctx: ExecutionContext) -> NodeResult:
    """
    Delay/wait step. Serverless functions can't block on time.sleep() for
    arbitrary durations without risking a function timeout, so this node
    always returns pending_external — api/cron/poll_jobs.py resumes the
    workflow once `resume_at` has elapsed.
    """
    seconds = ctx.config.get("seconds")
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds <= 0:
        return NodeResult(
            status="failed",
            error="delay: 'seconds' must be a positive number"
        )

    resume_at = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    return NodeResult(
        status="pending_external",
        external_ref={
            "provider": "delay",
            "resume_at": resume_at
        }
    )
