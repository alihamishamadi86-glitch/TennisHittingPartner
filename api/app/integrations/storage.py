"""Object storage for user uploads (profile photos).

Browsers upload directly to storage with a short-lived signed URL, so file bytes never pass
through the API. GCS in the cloud; a local-disk backend served by the API for development.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import google.auth
from google.auth.transport import requests as google_requests
from google.cloud import storage

from app.core.config import get_settings
from app.core.security import encode_signed

UPLOAD_URL_TTL = timedelta(minutes=10)


@dataclass(frozen=True)
class UploadTarget:
    url: str
    method: str = "PUT"
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    content_type: str


class Storage(Protocol):
    async def create_upload(
        self, object_name: str, content_type: str, max_bytes: int
    ) -> UploadTarget: ...

    async def stat(self, object_name: str) -> ObjectInfo | None: ...

    async def delete(self, object_name: str) -> None: ...

    def public_url(self, object_name: str) -> str: ...


class GcsStorage:
    def __init__(self, bucket: str) -> None:
        self._bucket_name = bucket
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket)

    def _signed_put_url(self, object_name: str, content_type: str, max_bytes: int) -> str:
        # On Cloud Run the runtime credentials have no private key; sign via the IAM
        # signBlob API using the service account's own identity and access token.
        credentials, _ = google.auth.default()
        credentials.refresh(google_requests.Request())  # type: ignore[no-untyped-call]
        url: str = self._bucket.blob(object_name).generate_signed_url(
            version="v4",
            expiration=UPLOAD_URL_TTL,
            method="PUT",
            content_type=content_type,
            headers={"x-goog-content-length-range": f"0,{max_bytes}"},
            service_account_email=getattr(credentials, "service_account_email", None),
            access_token=credentials.token,
        )
        return url

    async def create_upload(
        self, object_name: str, content_type: str, max_bytes: int
    ) -> UploadTarget:
        url = await asyncio.to_thread(self._signed_put_url, object_name, content_type, max_bytes)
        return UploadTarget(
            url=url,
            headers={
                "Content-Type": content_type,
                "x-goog-content-length-range": f"0,{max_bytes}",
            },
        )

    async def stat(self, object_name: str) -> ObjectInfo | None:
        blob = await asyncio.to_thread(self._bucket.get_blob, object_name)
        if blob is None:
            return None
        return ObjectInfo(size=blob.size or 0, content_type=blob.content_type or "")

    async def delete(self, object_name: str) -> None:
        await asyncio.to_thread(self._bucket.blob(object_name).delete)

    def public_url(self, object_name: str) -> str:
        return f"https://storage.googleapis.com/{self._bucket_name}/{object_name}"


class LocalStorage:
    """Development backend: uploads go to the API's /dev-storage routes, files live on disk."""

    def __init__(self, root: str, public_base_url: str) -> None:
        self.root = Path(root).resolve()
        self._base = public_base_url.rstrip("/")

    def path_for(self, object_name: str) -> Path | None:
        path = (self.root / object_name).resolve()
        return path if path.is_relative_to(self.root) and path != self.root else None

    async def create_upload(
        self, object_name: str, content_type: str, max_bytes: int
    ) -> UploadTarget:
        token = encode_signed(
            {"object": object_name, "content_type": content_type, "max_bytes": max_bytes},
            expected_type="upload",
            ttl=UPLOAD_URL_TTL,
        )
        return UploadTarget(
            url=f"{self._base}/dev-storage/upload/{token}", headers={"Content-Type": content_type}
        )

    def write(self, object_name: str, data: bytes, content_type: str) -> None:
        path = self.path_for(object_name)
        if path is None:
            raise ValueError("Invalid object name")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.with_name(path.name + ".meta").write_text(json.dumps({"content_type": content_type}))

    async def stat(self, object_name: str) -> ObjectInfo | None:
        path = self.path_for(object_name)
        if path is None or not path.is_file():
            return None
        meta = path.with_name(path.name + ".meta")
        content_type = json.loads(meta.read_text())["content_type"] if meta.exists() else ""
        return ObjectInfo(size=path.stat().st_size, content_type=content_type)

    async def delete(self, object_name: str) -> None:
        path = self.path_for(object_name)
        if path is not None:
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".meta").unlink(missing_ok=True)

    def public_url(self, object_name: str) -> str:
        return f"{self._base}/dev-storage/files/{object_name}"


@lru_cache
def get_storage() -> Storage:
    settings = get_settings()
    if settings.storage_backend == "gcs":
        return GcsStorage(settings.gcs_bucket)
    # Browser-facing base: the API is reached through the web app's /api proxy.
    return LocalStorage(settings.local_storage_dir, f"{settings.public_web_url}/api")
