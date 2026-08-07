"""Authenticated short-lived download URLs for private Flow Forge assets."""
import http.server
from api._lib.auth import is_authed
from api._lib.http_helpers import get_query_params, send_json
from api._lib.supabase_client import get_client

class handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if not is_authed(self): send_json(self, 401, {"error": "not authenticated"}); return
        asset_id = get_query_params(self).get("id")
        if not asset_id: send_json(self, 400, {"error": "asset id required"}); return
        sb = get_client()
        result = sb.table("generated_assets").select("id,storage_path,mime_type,is_persistent").eq("id", asset_id).execute().data
        bucket = "flowforge-assets"
        if not result:
            # Brand assets deliberately live in their own private bucket and do
            # not have rows in generated_assets.
            result = sb.table("brand_assets").select("id,storage_path,mime_type").eq("id", asset_id).execute().data
            bucket = "flowforge-brand-assets"
        if not result: send_json(self, 404, {"error": "asset not found"}); return
        asset = result[0]
        try:
            signed = sb.storage.from_(bucket).create_signed_url(asset["storage_path"], 300)
            send_json(self, 200, {"asset": {"id": asset["id"], "mime_type": asset.get("mime_type"), "name": asset["storage_path"].rsplit("/", 1)[-1], "url": signed.get("signedURL") or signed.get("signedUrl")}})
        except Exception as exc: send_json(self, 500, {"error": str(exc)})
