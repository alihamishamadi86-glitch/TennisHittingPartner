import logging
import secrets
from datetime import timedelta
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.config import Settings, get_settings
from app.core.cookies import (
    OAUTH_STATE_COOKIE,
    REFRESH_COOKIE,
    clear_session_cookies,
    delete_cookie,
    oauth_cookie_path,
    set_cookie,
    set_session_cookies,
)
from app.core.deps import ClientInfoDep, CurrentUser, SessionDep
from app.core.security import decode_signed, encode_signed, generate_token, is_safe_redirect_path
from app.events.outbox import commit_and_publish
from app.integrations.google_oauth import GoogleOAuth, GoogleOAuthError, get_google_oauth
from app.models import UserRole
from app.schemas.auth import (
    AuthProvidersOut,
    ForgotPasswordIn,
    LoginIn,
    RegisterIn,
    ResetPasswordIn,
    SelfServiceRole,
    TokenIn,
    UserOut,
)
from app.services import auth as auth_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

OAUTH_STATE_TTL = timedelta(minutes=10)
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _invalid_credentials() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")


@router.get("/providers")
async def providers(settings: SettingsDep) -> AuthProvidersOut:
    """Sign-in methods available in this environment (drives the login UI)."""
    return AuthProvidersOut(google=settings.google_enabled)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterIn, response: Response, session: SessionDep, client: ClientInfoDep
) -> UserOut:
    try:
        user = await auth_service.register_user(
            session,
            email=body.email,
            password=body.password,
            full_name=body.full_name,
            role=UserRole(body.role.value),
        )
    except auth_service.EmailTakenError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email exists") from exc
    tokens = await auth_service.issue_session(session, user, client)
    await commit_and_publish(session)
    set_session_cookies(response, tokens.access_token, tokens.refresh_token)
    return UserOut.from_user(user)


@router.post("/login")
async def login(
    body: LoginIn, response: Response, session: SessionDep, client: ClientInfoDep
) -> UserOut:
    try:
        user = await auth_service.authenticate(session, email=body.email, password=body.password)
    except auth_service.AccountLockedError as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts. Try again later."
        ) from exc
    except auth_service.InvalidCredentialsError as exc:
        await session.commit()  # persist the failed-attempt counter
        raise _invalid_credentials() from exc
    tokens = await auth_service.issue_session(session, user, client)
    await session.commit()
    set_session_cookies(response, tokens.access_token, tokens.refresh_token)
    return UserOut.from_user(user)


@router.post("/refresh", response_model=UserOut, responses={401: {"description": "No session"}})
async def refresh(
    response: Response,
    session: SessionDep,
    client: ClientInfoDep,
    refresh_cookie: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> UserOut | JSONResponse:
    if not refresh_cookie:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No session")
    try:
        user, tokens = await auth_service.rotate_refresh_token(session, refresh_cookie, client)
    except auth_service.InvalidTokenError:
        await session.commit()  # persist family revocation on token reuse
        expired = JSONResponse({"detail": "Session expired"}, status_code=401)
        clear_session_cookies(expired)
        return expired
    await session.commit()
    set_session_cookies(response, tokens.access_token, tokens.refresh_token)
    return UserOut.from_user(user)


@router.get("/session/renew", include_in_schema=False)
async def renew_session(
    session: SessionDep,
    client: ClientInfoDep,
    settings: SettingsDep,
    next_path: Annotated[str | None, Query(alias="next")] = None,
    refresh_cookie: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> RedirectResponse:
    """Browser-navigation variant of /refresh used by the web app's proxy: the refresh cookie is
    scoped to the auth path, so page requests can't refresh themselves. Rotates the session and
    redirects back to `next`, or to the login page when there is no valid session."""
    destination = next_path if is_safe_redirect_path(next_path) else "/dashboard"
    if refresh_cookie:
        try:
            _, tokens = await auth_service.rotate_refresh_token(session, refresh_cookie, client)
        except auth_service.InvalidTokenError:
            await session.commit()
        else:
            await session.commit()
            response = RedirectResponse(f"{settings.public_web_url}{destination}", status_code=302)
            set_session_cookies(response, tokens.access_token, tokens.refresh_token)
            return response
    response = RedirectResponse(
        f"{settings.public_web_url}/login?{urlencode({'next': destination})}", status_code=302
    )
    clear_session_cookies(response)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    session: SessionDep,
    refresh_cookie: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> Response:
    if refresh_cookie:
        await auth_service.revoke_session(session, refresh_cookie)
        await session.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(response)
    return response


@router.post("/verify-email")
async def verify_email(body: TokenIn, session: SessionDep) -> UserOut:
    try:
        user = await auth_service.verify_email(session, body.token)
    except auth_service.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link is invalid or has expired") from exc
    await session.commit()
    return UserOut.from_user(user)


@router.post("/verify-email/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(user: CurrentUser, session: SessionDep) -> None:
    await auth_service.request_email_verification(session, user)
    await commit_and_publish(session)


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(body: ForgotPasswordIn, session: SessionDep) -> None:
    await auth_service.request_password_reset(session, body.email)
    await commit_and_publish(session)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(body: ResetPasswordIn, session: SessionDep) -> Response:
    try:
        await auth_service.reset_password(session, body.token, body.password)
    except auth_service.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link is invalid or has expired") from exc
    await session.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(response)
    return response


# --- Google -----------------------------------------------------------------------------


@router.get("/google/login", include_in_schema=False)
async def google_login(
    settings: SettingsDep,
    google: Annotated[GoogleOAuth, Depends(get_google_oauth)],
    role: Annotated[SelfServiceRole | None, Query()] = None,
    next_path: Annotated[str | None, Query(alias="next")] = None,
) -> RedirectResponse:
    if not settings.google_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Google sign-in is not configured")
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), generate_token()
    cookie = encode_signed(
        {
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "role": role.value if role else None,
            "next": next_path if is_safe_redirect_path(next_path) else None,
        },
        expected_type="oauth_state",
        ttl=OAUTH_STATE_TTL,
    )
    response = RedirectResponse(google.authorization_url(state, nonce, verifier), status_code=302)
    set_cookie(
        response,
        OAUTH_STATE_COOKIE,
        cookie,
        max_age=int(OAUTH_STATE_TTL.total_seconds()),
        path=oauth_cookie_path(),
    )
    return response


@router.get("/google/callback", include_in_schema=False)
async def google_callback(
    session: SessionDep,
    client: ClientInfoDep,
    settings: SettingsDep,
    google: Annotated[GoogleOAuth, Depends(get_google_oauth)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth_cookie: Annotated[str | None, Cookie(alias=OAUTH_STATE_COOKIE)] = None,
) -> RedirectResponse:
    def finish(path: str) -> RedirectResponse:
        response = RedirectResponse(f"{settings.public_web_url}{path}", status_code=302)
        delete_cookie(response, OAUTH_STATE_COOKIE, path=oauth_cookie_path())
        return response

    def fail(reason: str) -> RedirectResponse:
        logger.warning("Google sign-in failed: %s", reason)
        return finish(f"/login?{urlencode({'error': 'google'})}")

    stored = decode_signed(oauth_cookie, "oauth_state") if oauth_cookie else None
    if error:
        return fail(f"provider error {error}")
    if not stored or not code or not state or not secrets.compare_digest(state, stored["state"]):
        return fail("state mismatch or missing code")

    try:
        identity = await google.exchange_code(code, stored["verifier"], stored["nonce"])
        role = UserRole(stored["role"]) if stored.get("role") else None
        user, _ = await auth_service.sign_in_with_google(session, identity, role)
    except GoogleOAuthError as exc:
        return fail(str(exc))
    except auth_service.GoogleEmailNotVerifiedError:
        return fail("google email not verified")
    except auth_service.InvalidCredentialsError:
        return fail("account inactive")

    tokens = await auth_service.issue_session(session, user, client)
    await commit_and_publish(session)

    if user.role is None:
        destination = "/onboarding/role"
    else:
        destination = stored.get("next") or "/dashboard"
    response = finish(destination)
    set_session_cookies(response, tokens.access_token, tokens.refresh_token)
    return response
