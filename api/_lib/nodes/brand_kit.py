"""Expose the selected reusable Brand Kit version to a workflow graph."""
from api._lib.nodes.base import Artifact, ExecutionContext, NodeResult, register_node

@register_node("data/brand_kit")
def run(ctx: ExecutionContext) -> NodeResult:
    kit_id = ctx.config.get("brand_kit_id") or ctx.inputs.get("brand_kit_id")
    if not kit_id: return NodeResult(status="failed", error="Brand Kit node requires brand_kit_id")
    try:
        kit = ctx.supabase.table("brand_kits").select("active_version_id").eq("id", kit_id).single().execute().data
        if not kit.get("active_version_id"): return NodeResult(status="failed", error="Brand Kit has no active version")
        version = ctx.supabase.table("brand_kit_versions").select("profile_json").eq("id", kit["active_version_id"]).single().execute().data
        profile = version["profile_json"] or {}; assets = ctx.supabase.table("brand_assets").select("id,storage_path,mime_type").eq("brand_kit_id", kit_id).execute().data
        # These references are consumed by provider nodes, not a browser.  They
        # therefore need a short-lived Storage URL rather than an authenticated
        # Flow Forge API URL (which an external provider could not read).
        artifacts = []
        for asset in assets:
            signed = ctx.supabase.storage.from_("flowforge-brand-assets").create_signed_url(asset["storage_path"], 300)
            artifacts.append(Artifact(
                kind="image", url=signed.get("signedURL") or signed.get("signedUrl"),
                mime_type=asset["mime_type"], provider="flowforge",
                metadata={"asset_id": asset["id"], "storage_path": asset["storage_path"]},
            ).to_dict())
        return NodeResult(status="success", outputs={"style_profile": profile, "prompt_prefix": profile.get("prompt_prefix", ""), "negative_prompt": profile.get("negative_prompt", ""), "reference_artifacts": artifacts}, artifacts=artifacts)
    except Exception as exc: return NodeResult(status="failed", error=f"Brand Kit lookup failed: {exc}")
