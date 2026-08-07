"""Authenticated Brand Kit CRUD with explicitly consented OpenRouter vision analysis."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
import http.server
import httpx

from api._lib.auth import is_authed
from api._lib.http_helpers import get_query_params, read_json_body, send_json
from api._lib.supabase_client import get_client

PROFILE_KEYS = ("summary", "palette", "lighting", "composition", "materials", "camera", "typography", "style_keywords", "prompt_prefix", "negative_prompt", "do", "avoid", "reference_asset_ids")
PROFILE_SCHEMA = {"name": "brand_profile", "strict": True, "schema": {"type": "object", "additionalProperties": False, "properties": {"summary": {"type": "string"}, "palette": {"type": "array", "items": {"type": "string"}}, "lighting": {"type": "string"}, "composition": {"type": "string"}, "materials": {"type": "string"}, "camera": {"type": "string"}, "typography": {"type": "string"}, "style_keywords": {"type": "array", "items": {"type": "string"}}, "prompt_prefix": {"type": "string"}, "negative_prompt": {"type": "string"}, "do": {"type": "array", "items": {"type": "string"}}, "avoid": {"type": "array", "items": {"type": "string"}}, "reference_asset_ids": {"type": "array", "items": {"type": "string"}}}, "required": list(PROFILE_KEYS)}}


def _actual_image_mime(raw: bytes) -> str | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if raw.startswith(b"\xff\xd8\xff"): return "image/jpeg"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP": return "image/webp"
    return None

class handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if not is_authed(self): send_json(self, 401, {"error": "not authenticated"}); return
        sb, query = get_client(), get_query_params(self); kit_id = query.get("id")
        if kit_id and query.get("action") == "versions":
            send_json(self, 200, {"versions": sb.table("brand_kit_versions").select("*").eq("brand_kit_id", kit_id).order("version_number", desc=True).execute().data}); return
        if kit_id:
            kit = sb.table("brand_kits").select("*").eq("id", kit_id).single().execute().data
            assets = sb.table("brand_assets").select("*").eq("brand_kit_id", kit_id).execute().data
            send_json(self, 200, {"brand_kit": kit, "assets": assets}); return
        send_json(self, 200, {"brand_kits": sb.table("brand_kits").select("*").order("updated_at", desc=True).execute().data})

    def do_POST(self):
        if not is_authed(self): send_json(self, 401, {"error": "not authenticated"}); return
        sb, body, query = get_client(), read_json_body(self), get_query_params(self); action, kit_id = query.get("action"), query.get("id")
        if action == "create":
            row = sb.table("brand_kits").insert({"name": str(body.get("name") or "Untitled Brand Kit")}).execute().data[0]; send_json(self, 201, {"brand_kit": row}); return
        if action == "asset" and kit_id:
            if len(sb.table("brand_assets").select("id").eq("brand_kit_id", kit_id).execute().data) >= 10: send_json(self, 400, {"error": "A Brand Kit has a 10-image limit"}); return
            mime, path = body.get("mime_type"), body.get("storage_path")
            if mime not in ("image/png", "image/jpeg", "image/webp") or not isinstance(path, str) or not path.startswith("pending/"):
                send_json(self, 400, {"error": "Invalid private Brand Kit asset"}); return
            try:
                raw = sb.storage.from_("flowforge-brand-assets").download(path)
            except Exception as exc:
                send_json(self, 400, {"error": f"Brand Kit upload could not be read: {exc}"}); return
            actual = _actual_image_mime(raw)
            if len(raw) < 1 or len(raw) > 10 * 1024 * 1024 or actual != mime:
                send_json(self, 400, {"error": "Uploaded file content does not match an allowed image type or size"}); return
            row = sb.table("brand_assets").insert({"brand_kit_id": kit_id, "storage_path": path, "mime_type": actual, "size_bytes": len(raw)}).execute().data[0]; send_json(self, 201, {"asset": row}); return
        if action == "profile" and kit_id:
            existing = sb.table("brand_kit_versions").select("version_number").eq("brand_kit_id", kit_id).order("version_number", desc=True).limit(1).execute().data
            row = sb.table("brand_kit_versions").insert({"brand_kit_id": kit_id, "version_number": (existing[0]["version_number"] if existing else 0) + 1, "profile_json": body.get("profile", {}), "prompt_version": "manual"}).execute().data[0]
            sb.table("brand_kits").update({"active_version_id": row["id"], "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", kit_id).execute(); send_json(self, 201, {"version": row}); return
        if action == "analyze" and kit_id:
            assets = sb.table("brand_assets").select("id,storage_path").eq("brand_kit_id", kit_id).execute().data
            if not assets: send_json(self, 400, {"error": "Add at least one Brand Kit image before analysis"}); return
            model = os.environ.get("BRAND_ANALYSIS_MODEL") or body.get("model")
            key = os.environ.get("OPENROUTER_API_KEY")
            if not model or not key: send_json(self, 503, {"error": "Configure BRAND_ANALYSIS_MODEL and OPENROUTER_API_KEY"}); return
            try:
                images = []
                for asset in assets:
                    signed = sb.storage.from_("flowforge-brand-assets").create_signed_url(asset["storage_path"], 3600)
                    images.append({"type": "image_url", "image_url": {"url": signed.get("signedURL") or signed.get("signedUrl")}})
                response = httpx.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json={"model": model, "messages": [{"role": "user", "content": [{"type": "text", "text": "Analyze these approved Brand Kit references and produce an editable creative style profile."}] + images}], "response_format": {"type": "json_schema", "json_schema": PROFILE_SCHEMA}}, timeout=90)
                response.raise_for_status(); raw = response.json(); profile = json.loads(raw["choices"][0]["message"]["content"])
                profile["reference_asset_ids"] = [asset["id"] for asset in assets]
                existing = sb.table("brand_kit_versions").select("version_number").eq("brand_kit_id", kit_id).order("version_number", desc=True).limit(1).execute().data
                usage = raw.get("usage") or {}
                row = sb.table("brand_kit_versions").insert({"brand_kit_id": kit_id, "version_number": (existing[0]["version_number"] if existing else 0) + 1, "profile_json": profile, "analysis_model": raw.get("model", model), "prompt_version": "vision-v1", "source_asset_ids": profile["reference_asset_ids"], "cost_usd": usage.get("cost", 0)}).execute().data[0]
                sb.table("brand_kits").update({"active_version_id": row["id"], "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", kit_id).execute(); send_json(self, 201, {"version": row}); return
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                send_json(self, 502, {"error": f"Brand analysis failed: {exc}"}); return
        send_json(self, 404, {"error": "not found"})
