import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import ClubKind, DiscoveryStatus


class CityDiscoverIn(BaseModel):
    city: str = Field(min_length=1, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    country_code: str = Field(default="US", pattern=r"^[A-Z]{2}$")


class CityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    region: str | None
    country_code: str
    lat: float
    lon: float
    status: DiscoveryStatus
    club_count: int
    discovered_at: datetime | None


class ClubOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    city_id: uuid.UUID
    name: str
    kind: ClubKind
    lat: float
    lon: float
    address: str | None
    website: str | None
    phone: str | None
    court_count: int | None
    surface: str | None
    access: str | None
    lit: bool | None
    distance_km: float | None = None


class PartnerClubsIn(BaseModel):
    club_ids: list[uuid.UUID] = Field(max_length=20)


class PartnerClubsOut(BaseModel):
    club_ids: list[uuid.UUID]
    clubs: list[ClubOut]
