"""Client and partner profiles, and the partner verification workflow."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.events.catalog import PARTNER_APPLICATION_SUBMITTED, PARTNER_VERIFICATION_DECIDED
from app.events.outbox import record_event
from app.models import (
    ClientProfile,
    PartnerProfile,
    PartnerStatus,
    PartnerVerification,
    User,
    UserRole,
)

MIN_BIO_LENGTH = 80

# Transitions an admin may make. Partners themselves only submit (draft/rejected → applied).
ADMIN_TRANSITIONS: dict[PartnerStatus, frozenset[PartnerStatus]] = {
    PartnerStatus.APPLIED: frozenset(
        {PartnerStatus.SCREENED, PartnerStatus.APPROVED, PartnerStatus.REJECTED}
    ),
    PartnerStatus.SCREENED: frozenset({PartnerStatus.APPROVED, PartnerStatus.REJECTED}),
    PartnerStatus.APPROVED: frozenset({PartnerStatus.REJECTED}),
}
SUBMITTABLE = frozenset({PartnerStatus.DRAFT, PartnerStatus.REJECTED})


class ProfileError(Exception):
    pass


class ProfileNotFoundError(ProfileError):
    pass


@dataclass(frozen=True)
class IncompleteApplicationError(ProfileError):
    missing: list[str]


class InvalidTransitionError(ProfileError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


async def is_profile_complete(session: AsyncSession, user: User) -> bool:
    if user.role is UserRole.CLIENT:
        return await session.get(ClientProfile, user.id) is not None
    if user.role is UserRole.PARTNER:
        profile = await session.get(PartnerProfile, user.id)
        return profile is not None and profile.status is not PartnerStatus.DRAFT
    return user.role is UserRole.ADMIN


async def upsert_client_profile(
    session: AsyncSession, user: User, fields: dict[str, Any]
) -> ClientProfile:
    profile = await session.get(ClientProfile, user.id)
    if profile is None:
        profile = ClientProfile(user_id=user.id, **fields)
        session.add(profile)
    else:
        for key, value in fields.items():
            setattr(profile, key, value)
    await session.flush()
    await session.refresh(profile)
    return profile


async def upsert_partner_profile(
    session: AsyncSession, user: User, fields: dict[str, Any]
) -> PartnerProfile:
    profile = await session.get(PartnerProfile, user.id)
    if profile is None:
        profile = PartnerProfile(user_id=user.id, status=PartnerStatus.DRAFT, **fields)
        session.add(profile)
    else:
        for key, value in fields.items():
            setattr(profile, key, value)
    await session.flush()
    await session.refresh(profile)
    return profile


def missing_for_application(user: User, profile: PartnerProfile) -> list[str]:
    missing = []
    if not user.avatar_url:
        missing.append("photo")
    if len(profile.bio.strip()) < MIN_BIO_LENGTH:
        missing.append("bio")
    if profile.background is None:
        missing.append("background")
    if profile.ntrp_rating < Decimal(str(get_settings().min_partner_ntrp)):
        missing.append("ntrp_rating")
    return missing


async def submit_partner_application(session: AsyncSession, user: User) -> PartnerProfile:
    profile = await session.get(PartnerProfile, user.id, with_for_update=True)
    if profile is None:
        raise ProfileNotFoundError
    if profile.status not in SUBMITTABLE:
        raise InvalidTransitionError
    if missing := missing_for_application(user, profile):
        raise IncompleteApplicationError(missing)

    session.add(
        PartnerVerification(
            partner_id=user.id, from_status=profile.status, to_status=PartnerStatus.APPLIED
        )
    )
    profile.status = PartnerStatus.APPLIED
    profile.submitted_at = _now()
    record_event(session, PARTNER_APPLICATION_SUBMITTED, {"partner_id": str(user.id)})
    await session.flush()
    await session.refresh(profile)
    return profile


async def decide_partner(
    session: AsyncSession,
    *,
    admin: User,
    partner_id: uuid.UUID,
    decision: PartnerStatus,
    note: str,
    verified_ntrp: Decimal | None,
) -> PartnerProfile:
    profile = await session.get(PartnerProfile, partner_id, with_for_update=True)
    if profile is None:
        raise ProfileNotFoundError
    if decision not in ADMIN_TRANSITIONS.get(profile.status, frozenset()):
        raise InvalidTransitionError
    if decision is PartnerStatus.APPROVED:
        if verified_ntrp is None:
            raise IncompleteApplicationError(["verified_ntrp_rating"])
        profile.verified_ntrp_rating = verified_ntrp
        profile.approved_at = _now()
    if decision is PartnerStatus.REJECTED:
        profile.approved_at = None

    session.add(
        PartnerVerification(
            partner_id=partner_id,
            from_status=profile.status,
            to_status=decision,
            actor_id=admin.id,
            note=note.strip(),
        )
    )
    profile.status = decision
    record_event(
        session,
        PARTNER_VERIFICATION_DECIDED,
        {"partner_id": str(partner_id), "status": decision.value, "note": note.strip()},
    )
    await session.flush()
    await session.refresh(profile)
    return profile


async def list_partner_applications(
    session: AsyncSession, status: PartnerStatus | None
) -> list[tuple[PartnerProfile, User]]:
    query = select(PartnerProfile, User).join(User, User.id == PartnerProfile.user_id)
    if status is not None:
        query = query.where(PartnerProfile.status == status)
    else:
        query = query.where(PartnerProfile.status != PartnerStatus.DRAFT)
    query = query.order_by(PartnerProfile.submitted_at.asc().nulls_last())
    return [(profile, user) for profile, user in (await session.execute(query)).all()]


async def verification_history(
    session: AsyncSession, partner_id: uuid.UUID
) -> list[PartnerVerification]:
    return list(
        (
            await session.scalars(
                select(PartnerVerification)
                .where(PartnerVerification.partner_id == partner_id)
                .order_by(PartnerVerification.created_at)
            )
        ).all()
    )


async def promote_to_admin(session: AsyncSession, email: str) -> User:
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        raise ProfileNotFoundError
    user.role = UserRole.ADMIN
    await session.flush()
    return user
