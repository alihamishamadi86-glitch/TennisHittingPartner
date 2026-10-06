"""Profile photo uploads: issue a signed upload target, then verify and attach the object."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations.storage import Storage, UploadTarget
from app.models import User

ALLOWED_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class PhotoError(Exception):
    pass


def _prefix(user: User) -> str:
    return f"profile-photos/{user.id}/"


async def create_photo_upload(
    storage: Storage, user: User, content_type: str, size: int
) -> tuple[str, UploadTarget]:
    max_bytes = get_settings().max_photo_bytes
    if content_type not in ALLOWED_TYPES:
        raise PhotoError("Use a JPEG, PNG or WebP image")
    if size <= 0 or size > max_bytes:
        raise PhotoError(f"Images must be smaller than {max_bytes // (1024 * 1024)} MB")
    object_name = f"{_prefix(user)}{uuid.uuid4().hex}.{ALLOWED_TYPES[content_type]}"
    return object_name, await storage.create_upload(object_name, content_type, max_bytes)


async def attach_photo(
    session: AsyncSession, storage: Storage, user: User, object_name: str
) -> User:
    """Verify the uploaded object belongs to the user and is an acceptable image, then use it."""
    if not object_name.startswith(_prefix(user)) or ".." in object_name:
        raise PhotoError("Invalid upload")
    info = await storage.stat(object_name)
    if info is None:
        raise PhotoError("Upload not found — please try again")
    if info.content_type not in ALLOWED_TYPES or info.size > get_settings().max_photo_bytes:
        await storage.delete(object_name)
        raise PhotoError("Invalid image")

    previous = user.avatar_url
    user.avatar_url = storage.public_url(object_name)
    await session.flush()

    # Best effort: remove the previous upload if it was one of ours (not e.g. a Google avatar).
    old_prefix = storage.public_url(_prefix(user))
    if previous and previous.startswith(old_prefix):
        await storage.delete(previous.removeprefix(storage.public_url("")))
    return user
