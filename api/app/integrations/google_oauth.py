"""Google Sign-In via OpenID Connect Authorization Code flow with PKCE (server-side)."""

import asyncio
import base64
import hashlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.core.config import get_settings

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 (endpoint URL, not a secret)


class GoogleOAuthError(Exception):
    pass


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    email_verified: bool
    name: str
    picture: str | None


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class GoogleOAuth(Protocol):
    def authorization_url(self, state: str, nonce: str, code_verifier: str) -> str: ...

    async def exchange_code(self, code: str, code_verifier: str, nonce: str) -> GoogleIdentity: ...


class GoogleOAuthClient:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._transport = google_requests.Request()

    def authorization_url(self, state: str, nonce: str, code_verifier: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, code_verifier: str, nonce: str) -> GoogleIdentity:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": self._redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
            )
        if response.status_code != 200:
            raise GoogleOAuthError(f"Token exchange failed ({response.status_code})")

        raw_id_token = response.json().get("id_token")
        if not raw_id_token:
            raise GoogleOAuthError("No id_token in token response")
        try:
            claims: dict[str, Any] = await asyncio.to_thread(
                id_token.verify_oauth2_token,  # checks signature, issuer, audience, expiry
                raw_id_token,
                self._transport,
                self._client_id,
            )
        except ValueError as exc:
            raise GoogleOAuthError(f"Invalid id_token: {exc}") from exc
        if claims.get("nonce") != nonce:
            raise GoogleOAuthError("Nonce mismatch")

        return GoogleIdentity(
            subject=claims["sub"],
            email=claims["email"].lower(),
            email_verified=bool(claims.get("email_verified")),
            name=claims.get("name", ""),
            picture=claims.get("picture"),
        )


@lru_cache
def get_google_oauth() -> GoogleOAuth:
    settings = get_settings()
    return GoogleOAuthClient(
        settings.google_client_id,
        settings.google_client_secret.get_secret_value(),
        settings.google_redirect_uri,
    )
