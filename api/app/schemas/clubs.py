import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import ClubKind, DiscoveryStatus

PostalCodeStr = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9 -]{1,11}$")


class CityDiscoverIn(BaseModel):
    """A city, a postal code, or both. A postal code also focuses results around it."""

    city: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    postal_code: str | None = PostalCodeStr
    country_code: str = Field(default="US", pattern=r"^[A-Z]{2}$")

    @field_validator("postal_code", mode="before")
    @classmethod
    def _normalize_postcode(cls, value: object) -> object:
        return " ".join(value.upper().split()) or None if isinstance(value, str) else value

    @model_validator(mode="after")
    def _city_or_postcode(self) -> "CityDiscoverIn":
        self.city = (self.city or "").strip() or None
        self.region = (self.region or "").strip() or None
        if not self.city and not self.postal_code:
            raise ValueError("Enter a city or a postal code")
        return self


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


class FocusOut(BaseModel):
    """Where to centre results: the geocoded postal code."""

    postal_code: str
    lat: float
    lon: float


class DiscoveryOut(BaseModel):
    city: CityOut
    focus: FocusOut | None = None


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
