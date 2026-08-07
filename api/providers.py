"""Authenticated provider catalog endpoint, consolidated to limit Vercel functions."""
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
import http.server
import httpx

from api._lib.auth import is_authed
from api._lib.http_helpers import get_query_params, send_json
from api._lib.supabase_client import get_client


def _now(): return datetime.now(timezone.utc)


def _provider_from_path(handler):
    # Vercel rewrites /api/providers/<provider>/models to this function with
    # ``?provider=<provider>``.  Keep the path fallback for local development.
    provider = get_query_params(handler).get("provider")
    if provider:
        return provider
    parts = [part for part in urlparse(handler.path).path.split("/") if part]
    return parts[2] if len(parts) >= 4 and parts[:2] == ["api", "providers"] else None


def _openrouter_models():
    # The dedicated APIs include image/video-only models that the generic
    # catalog does not consistently surface with their parameter descriptors.
    results = []
    for url, modality in (("https://openrouter.ai/api/v1/models", "text"), ("https://openrouter.ai/api/v1/images/models", "image"), ("https://openrouter.ai/api/v1/videos/models", "video")):
        response = httpx.get(url, timeout=20); response.raise_for_status()
        for model in response.json().get("data", []):
            model = dict(model); model.setdefault("architecture", {})
            model["architecture"].setdefault("output_modalities", [modality])
            results.append(model)
    return results


def _fal_models():
    headers = {"Authorization": f"Key {os.environ['FAL_KEY']}"} if os.environ.get("FAL_KEY") else {}
    response = httpx.get("https://api.fal.ai/v1/models", headers=headers, params={"expand": "openapi-3.0"}, timeout=30)
    response.raise_for_status()
    return response.json().get("models", [])


class handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if not is_authed(self):
            send_json(self, 401, {"error": "not authenticated"}); return
        provider = _provider_from_path(self)
        if provider not in ("openrouter", "fal"):
            send_json(self, 404, {"error": "unknown provider"}); return
        query = parse_qs(urlparse(self.path).query)
        force = query.get("refresh", ["false"])[0] == "true"
        modality = query.get("modality", [None])[0]
        sb = get_client()
        try:
            cached = sb.table("provider_models").select("*").eq("provider", provider).gt("expires_at", _now().isoformat()).execute().data
            if cached and not force:
                rows = cached
            else:
                raw_models = _openrouter_models() if provider == "openrouter" else _fal_models()
                expires_at = (_now() + timedelta(hours=6)).isoformat()
                rows = []
                for raw in raw_models:
                    slug = raw.get("id") if provider == "openrouter" else raw.get("endpoint_id")
                    meta = raw.get("metadata", {}) if provider == "fal" else raw
                    if not slug: continue
                    detected = (meta.get("category") or ",".join(raw.get("architecture", {}).get("output_modalities", [])) or "text")
                    capability = {"supported_parameters": raw.get("supported_parameters", []), "architecture": raw.get("architecture", {}), "openapi": raw.get("openapi")}
                    row = {"provider": provider, "model_slug": slug, "modality": detected, "capabilities_json": capability, "raw_json": raw, "fetched_at": _now().isoformat(), "expires_at": expires_at}
                    sb.table("provider_models").upsert(row, on_conflict="provider,model_slug").execute()
                    rows.append(row)
            if modality:
                rows = [row for row in rows if modality.lower() in (row.get("modality") or "").lower()]
            send_json(self, 200, {"provider": provider, "models": rows, "cached": bool(cached and not force)})
        except httpx.HTTPError as exc:
            send_json(self, 502, {"error": f"provider catalog unavailable: {exc}"})
        except Exception as exc:
            send_json(self, 500, {"error": str(exc)})
