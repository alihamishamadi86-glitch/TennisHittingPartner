"""Local stand-in for signed GCS uploads. Mounted only when STORAGE_BACKEND=local."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse

from app.core.security import decode_signed
from app.integrations.storage import LocalStorage, Storage, get_storage

router = APIRouter(prefix="/dev-storage", include_in_schema=False)


def local_storage(storage: Annotated[Storage, Depends(get_storage)]) -> LocalStorage:
    if not isinstance(storage, LocalStorage):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return storage


LocalStorageDep = Annotated[LocalStorage, Depends(local_storage)]


@router.put("/upload/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def upload(token: str, request: Request, storage: LocalStorageDep) -> Response:
    claims = decode_signed(token, "upload")
    if claims is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Upload URL expired or invalid")
    if request.headers.get("content-type") != claims["content_type"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Content-Type mismatch")

    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > claims["max_bytes"]:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large")
    storage.write(claims["object"], bytes(data), claims["content_type"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/files/{object_name:path}")
async def serve(object_name: str, storage: LocalStorageDep) -> FileResponse:
    info = await storage.stat(object_name)
    path = storage.path_for(object_name)
    if info is None or path is None or object_name.endswith(".meta"):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return FileResponse(path, media_type=info.content_type)
