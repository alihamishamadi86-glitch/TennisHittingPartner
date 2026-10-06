import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cookies import ACCESS_COOKIE
from app.core.db import get_session
from app.core.security import decode_access_token
from app.models import User, UserRole
from app.services.auth import ClientInfo

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    access_cookie: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Authenticate from the access cookie (browser) or a Bearer header (API clients).

    The user is loaded on every request so role changes and deactivation apply immediately.
    """
    token = access_cookie
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
    user_id: uuid.UUID | None = decode_access_token(token) if token else None
    user = await session.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], Awaitable[User]]:
    async def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return dependency


def get_client_info(request: Request) -> ClientInfo:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip: str | None = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else None
    return ClientInfo(user_agent=request.headers.get("user-agent"), ip_address=ip)


ClientInfoDep = Annotated[ClientInfo, Depends(get_client_info)]
