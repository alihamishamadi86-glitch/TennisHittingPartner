import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models import User, UserRole

Password = Field(min_length=10, max_length=128)


class SelfServiceRole(enum.StrEnum):
    """Roles a user can pick themselves; `admin` is never self-assigned."""

    CLIENT = "client"
    PARTNER = "partner"


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Password
    full_name: str = Field(min_length=1, max_length=200)
    role: SelfServiceRole

    @model_validator(mode="after")
    def _password_not_email(self) -> "RegisterIn":
        if self.password.strip().lower() == self.email.lower():
            raise ValueError("Password must not be your email address")
        return self


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Password


class RoleIn(BaseModel):
    role: SelfServiceRole


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    email_verified: bool
    role: UserRole | None
    full_name: str
    avatar_url: str | None
    has_password: bool
    # Onboarding done: client profile saved, or partner application submitted.
    profile_complete: bool
    created_at: datetime

    @classmethod
    def from_user(cls, user: User, profile_complete: bool = False) -> "UserOut":
        return cls(
            id=user.id,
            email=user.email,
            email_verified=user.is_email_verified,
            role=user.role,
            full_name=user.full_name,
            avatar_url=user.avatar_url,
            has_password=user.password_hash is not None,
            profile_complete=profile_complete,
            created_at=user.created_at,
        )


class AuthProvidersOut(BaseModel):
    password: bool = True
    google: bool
