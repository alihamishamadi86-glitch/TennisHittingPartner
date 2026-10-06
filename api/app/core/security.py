import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings

_hasher = PasswordHasher()
# Verified against when the user does not exist, so login timing doesn't reveal registered emails.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def generate_token() -> str:
    """Opaque high-entropy token for refresh tokens and email links."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Tokens are stored hashed; SHA-256 suffices because they are random, not user-chosen."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "typ": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID | None:
    claims = decode_signed(token, expected_type="access")
    if claims is None:
        return None
    try:
        return uuid.UUID(claims["sub"])
    except (KeyError, ValueError):
        return None


def encode_signed(payload: dict[str, Any], expected_type: str, ttl: timedelta) -> str:
    """Short-lived signed blob (e.g. OAuth state cookie)."""
    now = datetime.now(UTC)
    body = {**payload, "typ": expected_type, "iat": now, "exp": now + ttl}
    return jwt.encode(body, get_settings().jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_signed(token: str, expected_type: str) -> dict[str, Any] | None:
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            get_settings().jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "iat", "typ"]},
        )
    except jwt.PyJWTError:
        return None
    return claims if claims.get("typ") == expected_type else None


def is_safe_redirect_path(path: str | None) -> bool:
    """Only same-site relative paths: blocks `//evil.com`, `/\\evil.com` and absolute URLs."""
    if not path:
        return False
    return path.startswith("/") and not path.startswith(("//", "/\\"))
