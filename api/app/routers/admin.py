import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import SessionDep, require_roles
from app.events.outbox import commit_and_publish
from app.models import PartnerProfile, PartnerStatus, User, UserRole
from app.routers.profiles import partner_out
from app.schemas.profiles import (
    PartnerApplicationDetailOut,
    PartnerApplicationOut,
    PartnerDecisionIn,
    VerificationOut,
)
from app.services import profiles

router = APIRouter(prefix="/admin", tags=["admin"])

AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


def application_out(profile: PartnerProfile, user: User) -> PartnerApplicationOut:
    return PartnerApplicationOut(
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        avatar_url=user.avatar_url,
        status=profile.status,
        ntrp_rating=profile.ntrp_rating,
        verified_ntrp_rating=profile.verified_ntrp_rating,
        background=profile.background,
        city=profile.city,
        region=profile.region,
        submitted_at=profile.submitted_at,
    )


async def application_detail(
    session: SessionDep, partner_id: uuid.UUID
) -> PartnerApplicationDetailOut:
    profile = await session.get(PartnerProfile, partner_id)
    user = await session.get(User, partner_id)
    if profile is None or user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Partner not found")
    history = await profiles.verification_history(session, partner_id)
    return PartnerApplicationDetailOut(
        **application_out(profile, user).model_dump(),
        profile=partner_out(user, profile),
        history=[VerificationOut.model_validate(h) for h in history],
    )


@router.get("/partners")
async def list_partners(
    _: AdminUser,
    session: SessionDep,
    status_filter: Annotated[PartnerStatus | None, Query(alias="status")] = None,
) -> list[PartnerApplicationOut]:
    """Partner applications, oldest submission first. Drafts are excluded unless requested."""
    rows = await profiles.list_partner_applications(session, status_filter)
    return [application_out(profile, user) for profile, user in rows]


@router.get("/partners/{partner_id}")
async def get_partner(
    partner_id: uuid.UUID, _: AdminUser, session: SessionDep
) -> PartnerApplicationDetailOut:
    return await application_detail(session, partner_id)


@router.post("/partners/{partner_id}/decision")
async def decide(
    partner_id: uuid.UUID, body: PartnerDecisionIn, admin: AdminUser, session: SessionDep
) -> PartnerApplicationDetailOut:
    try:
        await profiles.decide_partner(
            session,
            admin=admin,
            partner_id=partner_id,
            decision=PartnerStatus(body.decision.value),
            note=body.note,
            verified_ntrp=body.verified_ntrp_rating,
        )
    except profiles.ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Partner not found") from exc
    except profiles.InvalidTransitionError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That decision isn't allowed from the current status"
        ) from exc
    except profiles.IncompleteApplicationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Set the verified NTRP rating to approve"
        ) from exc
    await commit_and_publish(session)
    return await application_detail(session, partner_id)
