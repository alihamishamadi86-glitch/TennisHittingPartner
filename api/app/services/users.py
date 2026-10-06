from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.schemas.auth import UserOut
from app.services.profiles import is_profile_complete


async def to_user_out(session: AsyncSession, user: User) -> UserOut:
    return UserOut.from_user(user, profile_complete=await is_profile_complete(session, user))
