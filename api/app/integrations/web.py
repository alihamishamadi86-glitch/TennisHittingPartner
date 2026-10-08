"""Polite, SSRF-safe fetching of third-party web pages (club websites).

URLs come from crowd-sourced data (OpenStreetMap, search results), so they are untrusted:
  - only http(s) on default ports;
  - every hostname — including each redirect hop — must resolve to public addresses only
    (no loopback, private, link-local/metadata, multicast or reserved ranges);
  - robots.txt is honoured for our user agent;
  - responses are size-capped and must be HTML.

Residual risk: DNS can change between our check and httpx's own lookup (rebinding). On Cloud
Run there is no private network to reach, and the metadata server rejects requests without a
`Metadata-Flavor: Google` header, which we never send.
"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.core.config import get_settings

MAX_BYTES = 1_000_000
MAX_REDIRECTS = 4
TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class FetchError(Exception):
    pass


class FetchBlocked(FetchError):
    """Refused for safety or politeness (private address, robots.txt, not HTML)."""


@dataclass(frozen=True)
class _Fetched:
    url: str
    status: int
    content_type: str
    text: str


@dataclass(frozen=True)
class Page:
    url: str  # final URL after redirects
    html: str


def _public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def _check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise FetchBlocked(f"Unsupported URL: {url}")
    if parts.port not in (None, 80, 443):
        raise FetchBlocked("Non-standard port")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            parts.hostname,
            parts.port or (443 if parts.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise FetchError(f"DNS lookup failed for {parts.hostname}") from exc
    addresses = {str(info[4][0]) for info in infos}
    if not addresses or not all(_public_ip(a) for a in addresses):
        raise FetchBlocked(f"{parts.hostname} resolves to a non-public address")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=False,  # each hop is checked by hand
        headers={
            "User-Agent": get_settings().geo_user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en,*;q=0.5",
        },
    )


async def _get(client: httpx.AsyncClient, url: str) -> _Fetched:
    for _ in range(MAX_REDIRECTS + 1):
        await _check_url(url)
        try:
            async with client.stream("GET", url) as response:
                if response.is_redirect and "location" in response.headers:
                    url = urljoin(url, response.headers["location"])
                    continue
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        break
                encoding = response.encoding or "utf-8"
                return _Fetched(
                    url=str(response.url),
                    status=response.status_code,
                    content_type=response.headers.get("content-type", ""),
                    text=bytes(body).decode(encoding, errors="replace"),
                )
        except httpx.HTTPError as exc:
            raise FetchError(f"{url}: {exc!r}") from exc
    raise FetchError("Too many redirects")


async def _allowed_by_robots(client: httpx.AsyncClient, url: str) -> bool:
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        response = await _get(client, robots_url)
    except FetchBlocked:
        raise
    except FetchError:
        return True  # unreachable robots.txt: treat as no restrictions (RFC 9309)
    if response.status >= 400:
        return True
    parser = RobotFileParser()
    parser.parse(response.text.splitlines())
    return parser.can_fetch(get_settings().geo_user_agent, url)


async def fetch_pages(urls: list[str]) -> list[Page]:
    """Fetch HTML pages from one site, checking robots.txt once per host."""
    pages: list[Page] = []
    async with _client() as client:
        robots: dict[str, bool] = {}
        for url in urls:
            host = urlsplit(url).netloc
            if host not in robots:
                robots[host] = await _allowed_by_robots(client, url)
            if not robots[host]:
                raise FetchBlocked(f"robots.txt disallows {url}")
            response = await _get(client, url)
            if response.status >= 400:
                continue
            if response.content_type and "html" not in response.content_type:
                continue
            pages.append(Page(response.url, response.text))
    return pages
