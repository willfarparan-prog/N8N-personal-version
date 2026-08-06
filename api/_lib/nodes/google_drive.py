"""Google Drive nodes for handing generated assets to a connected Drive.

The connector deliberately requests ``drive.file`` rather than broad full-Drive
access. That means it works with files FlowForge creates or that the user has
explicitly shared/opened with the app, which is the right default for a personal
creative-workflow tool.
"""
from __future__ import annotations

import json
import mimetypes
import uuid
from typing import Any

import httpx

from api._lib.google_oauth import GoogleOAuthError, google_access_token
from api._lib.nodes.base import ExecutionContext, NodeResult, register_node

DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"


def _error(prefix: str, exc: Exception) -> NodeResult:
    return NodeResult(status="failed", error=f"{prefix}: {exc}")


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {google_access_token()}"}


def _response_json(response: httpx.Response, prefix: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        detail = ""
        try:
            detail = response.json().get("error", {}).get("message", "")
        except Exception:
            pass
        raise GoogleOAuthError(f"{prefix}{': ' + detail if detail else ''}") from exc


@register_node("action/google_drive_upload")
def upload(ctx: ExecutionContext) -> NodeResult:
    """Upload a generated image or plain text payload to the connected Drive."""
    source_url = str(ctx.inputs.get("file_url") or ctx.config.get("file_url") or "").strip()
    text_content = ctx.inputs.get("content", ctx.config.get("content", ""))
    name = str(ctx.config.get("name") or "flowforge-output").strip()
    folder_id = str(ctx.config.get("folder_id") or "").strip()
    configured_mime = str(ctx.config.get("mime_type") or "").strip()
    if not source_url and text_content in (None, ""):
        return NodeResult(status="failed", error="google_drive_upload: connect file_url or provide content")

    try:
        if source_url:
            if not source_url.startswith(("https://", "http://")):
                raise GoogleOAuthError("file_url must be an http or https URL")
            downloaded = httpx.get(source_url, follow_redirects=True, timeout=45)
            downloaded.raise_for_status()
            data = downloaded.content
            mime_type = configured_mime or downloaded.headers.get("content-type", "").split(";", 1)[0] or mimetypes.guess_type(source_url)[0] or "application/octet-stream"
        else:
            data = str(text_content).encode("utf-8")
            mime_type = configured_mime or "text/plain"

        metadata: dict[str, Any] = {"name": name}
        if folder_id:
            metadata["parents"] = [folder_id]
        boundary = f"flowforge-{uuid.uuid4().hex}"
        body = b"\r\n".join([
            f"--{boundary}".encode(),
            b"Content-Type: application/json; charset=UTF-8",
            b"",
            json.dumps(metadata).encode("utf-8"),
            f"--{boundary}".encode(),
            f"Content-Type: {mime_type}".encode(),
            b"",
            data,
            f"--{boundary}--".encode(),
            b"",
        ])
        response = httpx.post(
            DRIVE_UPLOAD_URL,
            params={"uploadType": "multipart", "fields": "id,name,mimeType,webViewLink"},
            headers={**_headers(), "Content-Type": f"multipart/related; boundary={boundary}"},
            content=body,
            timeout=60,
        )
        file = _response_json(response, "Google Drive upload failed")
        return NodeResult(status="success", outputs={
            "file_id": file.get("id"),
            "file_url": file.get("webViewLink"),
            "file": file,
        })
    except (GoogleOAuthError, httpx.HTTPError) as exc:
        return _error("google_drive_upload", exc)


@register_node("action/google_drive_search")
def search(ctx: ExecutionContext) -> NodeResult:
    """Find files FlowForge is authorized to use in Google Drive."""
    query = str(ctx.config.get("query") or "trashed = false")
    page_size = min(max(int(ctx.config.get("page_size") or 20), 1), 100)
    try:
        response = httpx.get(
            DRIVE_FILES_URL,
            params={
                "q": query,
                "pageSize": page_size,
                "fields": "files(id,name,mimeType,modifiedTime,webViewLink,thumbnailLink),nextPageToken",
                "orderBy": "modifiedTime desc",
            },
            headers=_headers(),
            timeout=20,
        )
        payload = _response_json(response, "Google Drive search failed")
        return NodeResult(status="success", outputs={
            "files": payload.get("files", []),
            "next_page_token": payload.get("nextPageToken"),
        })
    except (GoogleOAuthError, httpx.HTTPError, ValueError) as exc:
        return _error("google_drive_search", exc)


@register_node("action/google_drive_folder")
def create_folder(ctx: ExecutionContext) -> NodeResult:
    """Create a folder for a workflow's generated files."""
    name = str(ctx.config.get("name") or "").strip()
    parent_folder_id = str(ctx.config.get("parent_folder_id") or "").strip()
    if not name:
        return NodeResult(status="failed", error="google_drive_folder: folder name is required")
    body: dict[str, Any] = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_folder_id:
        body["parents"] = [parent_folder_id]
    try:
        response = httpx.post(
            DRIVE_FILES_URL,
            params={"fields": "id,name,mimeType,webViewLink"},
            headers={**_headers(), "Content-Type": "application/json"},
            json=body,
            timeout=20,
        )
        folder = _response_json(response, "Google Drive folder creation failed")
        return NodeResult(status="success", outputs={
            "folder_id": folder.get("id"),
            "folder_url": folder.get("webViewLink"),
            "folder": folder,
        })
    except (GoogleOAuthError, httpx.HTTPError) as exc:
        return _error("google_drive_folder", exc)
