"""Verification of Google-signed OIDC tokens on push endpoints.

Pub/Sub push subscriptions, Cloud Scheduler and Cloud Tasks are configured to attach an
OIDC token minted for a dedicated service account. The worker accepts only those tokens.
"""

import asyncio
import logging
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_transport = google_requests.Request()


def _verify(token: str, audience: str) -> dict[str, Any]:
    claims: dict[str, Any] = id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
        token, _transport, audience=audience
    )
    return claims


async def verify_push_request(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if not settings.push_auth_enabled:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        claims = await asyncio.to_thread(
            _verify, authorization.removeprefix("Bearer "), settings.push_auth_audience
        )
    except ValueError as exc:
        logger.warning("Rejected push token: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    if not claims.get("email_verified") or claims.get("email") not in (
        settings.push_auth_allowed_emails
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Caller not allowed")
