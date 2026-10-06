from fastapi import Response

from app.core.config import get_settings

ACCESS_COOKIE = "thp_access"
REFRESH_COOKIE = "thp_refresh"
OAUTH_STATE_COOKIE = "thp_oauth"


def set_cookie(response: Response, key: str, value: str, *, max_age: int, path: str) -> None:
    response.set_cookie(
        key,
        value,
        max_age=max_age,
        path=path,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
    )


def delete_cookie(response: Response, key: str, *, path: str) -> None:
    response.delete_cookie(
        key, path=path, httponly=True, secure=get_settings().cookie_secure, samesite="lax"
    )


def set_session_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    settings = get_settings()
    set_cookie(
        response,
        ACCESS_COOKIE,
        access_token,
        max_age=settings.access_token_ttl_minutes * 60,
        path="/",
    )
    set_cookie(
        response,
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.refresh_token_ttl_days * 86400,
        path=settings.auth_cookie_path,
    )


def clear_session_cookies(response: Response) -> None:
    delete_cookie(response, ACCESS_COOKIE, path="/")
    delete_cookie(response, REFRESH_COOKIE, path=get_settings().auth_cookie_path)


def oauth_cookie_path() -> str:
    return f"{get_settings().auth_cookie_path}/google"
