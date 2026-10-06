from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import CurrentUser, SessionDep, require_roles
from app.events.outbox import commit_and_publish
from app.integrations.storage import Storage, get_storage
from app.models import ClientProfile, PartnerProfile, User, UserRole
from app.schemas.auth import UserOut
from app.schemas.profiles import (
    ClientProfileIn,
    ClientProfileOut,
    PartnerProfileIn,
    PartnerProfileOut,
    PhotoAttachIn,
    PhotoUploadIn,
    PhotoUploadOut,
)
from app.services import photos, profiles
from app.services.users import to_user_out

router = APIRouter(prefix="/me", tags=["profiles"])

ClientUser = Annotated[User, Depends(require_roles(UserRole.CLIENT))]
PartnerUser = Annotated[User, Depends(require_roles(UserRole.PARTNER))]
StorageDep = Annotated[Storage, Depends(get_storage)]


def partner_out(user: User, profile: PartnerProfile) -> PartnerProfileOut:
    out = PartnerProfileOut.model_validate(profile)
    out.missing_for_application = profiles.missing_for_application(user, profile)
    return out


@router.get("/client-profile", responses={404: {"description": "Not created yet"}})
async def get_client_profile(user: ClientUser, session: SessionDep) -> ClientProfileOut:
    profile = await session.get(ClientProfile, user.id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not created yet")
    return ClientProfileOut.model_validate(profile)


@router.put("/client-profile")
async def save_client_profile(
    body: ClientProfileIn, user: ClientUser, session: SessionDep
) -> ClientProfileOut:
    profile = await profiles.upsert_client_profile(session, user, body.model_dump())
    await session.commit()
    return ClientProfileOut.model_validate(profile)


@router.get("/partner-profile", responses={404: {"description": "Not created yet"}})
async def get_partner_profile(user: PartnerUser, session: SessionDep) -> PartnerProfileOut:
    profile = await session.get(PartnerProfile, user.id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not created yet")
    return partner_out(user, profile)


@router.put("/partner-profile")
async def save_partner_profile(
    body: PartnerProfileIn, user: PartnerUser, session: SessionDep
) -> PartnerProfileOut:
    """Save the partner profile. Edits are allowed in any status; the verified level stays as
    the agency set it."""
    profile = await profiles.upsert_partner_profile(session, user, body.model_dump())
    await session.commit()
    return partner_out(user, profile)


@router.post("/partner-profile/submit")
async def submit_partner_profile(user: PartnerUser, session: SessionDep) -> PartnerProfileOut:
    try:
        profile = await profiles.submit_partner_application(session, user)
    except profiles.ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Save your profile first") from exc
    except profiles.InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Application already submitted") from exc
    except profiles.IncompleteApplicationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"message": "Application is incomplete", "missing": exc.missing},
        ) from exc
    await commit_and_publish(session)
    return partner_out(user, profile)


@router.post("/photo/upload-url")
async def create_photo_upload(
    body: PhotoUploadIn, user: CurrentUser, storage: StorageDep
) -> PhotoUploadOut:
    try:
        object_name, target = await photos.create_photo_upload(
            storage, user, body.content_type, body.size
        )
    except photos.PhotoError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return PhotoUploadOut(
        object_name=object_name, upload_url=target.url, method=target.method, headers=target.headers
    )


@router.put("/photo")
async def attach_photo(
    body: PhotoAttachIn, user: CurrentUser, session: SessionDep, storage: StorageDep
) -> UserOut:
    try:
        await photos.attach_photo(session, storage, user, body.object_name)
    except photos.PhotoError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()
    return await to_user_out(session, user)
