"""Finding a club's official website: Wikidata, and optionally a web search API."""

import re
from functools import lru_cache
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from app.core.config import get_settings

WIKIDATA_ENTITY = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
BRAVE_SEARCH = "https://api.search.brave.com/res/v1/web/search"
QID = re.compile(r"^Q\d+$")

# Directories, socials and maps are not a club's own website.
NOT_OFFICIAL = (
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "tripadvisor.",
    "yelp.",
    "google.",
    "wikipedia.org",
    "wikidata.org",
    "openstreetmap.org",
    "foursquare.com",
    "linkedin.com",
    "youtube.com",
    "tiktok.com",
    "mapquest.com",
    "yellowpages",
    "paginasamarillas",
    "booking.com",
    "playtomic.io",
)


def is_official_candidate(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return bool(host) and not any(bad in host for bad in NOT_OFFICIAL)


def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        headers={"User-Agent": get_settings().geo_user_agent},
    )


async def wikidata_official_website(qid: str) -> str | None:
    """Wikidata property P856 ("official website")."""
    if not QID.match(qid):
        return None
    try:
        async with _http() as client:
            response = await client.get(WIKIDATA_ENTITY.format(qid=qid))
        data: dict[str, Any] = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    entity: dict[str, Any] = next(iter(data.get("entities", {}).values()), {})
    for claim in entity.get("claims", {}).get("P856", []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, str) and value.startswith("http"):
            return value
    return None


class WebsiteSearch(Protocol):
    async def find(self, name: str, city: str, country_code: str) -> str | None: ...


class BraveWebsiteSearch:
    """Brave Search API (free tier available). Returns the first non-directory result."""

    def __init__(self, api_key: str) -> None:
        self._key = api_key

    async def find(self, name: str, city: str, country_code: str) -> str | None:
        try:
            async with _http() as client:
                response = await client.get(
                    BRAVE_SEARCH,
                    params={"q": f'"{name}" {city} tennis', "count": 5, "country": country_code},
                    headers={"X-Subscription-Token": self._key, "Accept": "application/json"},
                )
            results = response.json().get("web", {}).get("results", [])
        except (httpx.HTTPError, ValueError):
            return None
        for result in results:
            url = result.get("url", "")
            if url.startswith("http") and is_official_candidate(url):
                return str(url)
        return None


@lru_cache
def get_website_search() -> WebsiteSearch | None:
    key = get_settings().brave_search_api_key.get_secret_value().strip()
    return BraveWebsiteSearch(key) if key else None
