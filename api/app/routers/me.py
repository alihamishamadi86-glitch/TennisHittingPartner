from fastapi import APIRouter, HTTPException, status

from app.core.deps import CurrentUser, SessionDep
from app.models import UserRole
from app.schemas.auth import RoleIn, UserOut
from app.services import auth as auth_service
from app.services.users import to_user_out

router = APIRouter(prefix="/me", tags=["me"])


@router.get("")
async def get_me(user: CurrentUser, session: SessionDep) -> UserOut:
    return await to_user_out(session, user)


@router.put("/role")
async def choose_role(body: RoleIn, user: CurrentUser, session: SessionDep) -> UserOut:
    """One-time role choice for accounts created via Google without a role."""
    try:
        await auth_service.set_role(session, user, UserRole(body.role.value))
    except auth_service.RoleNotAllowedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Role has already been chosen") from exc
    await session.commit()
    return await to_user_out(session, user)
