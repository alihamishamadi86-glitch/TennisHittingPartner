import enum
import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geography, WKBElement
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DiscoveryStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class ClubKind(enum.StrEnum):
    CLUB = "club"
    SPORTS_CENTRE = "sports_centre"
    PUBLIC_COURTS = "public_courts"


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class City(TimestampMixin, Base):
    """A geocoded city and the state of its club discovery."""

    __tablename__ = "cities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    region: Mapped[str | None] = mapped_column(String(120))
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    # Normalized "name|region|country" — one row per real city.
    key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    # Search area (south, west, north, east).
    bbox_south: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_west: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_north: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_east: Mapped[float] = mapped_column(Float, nullable=False)
    geocoder: Mapped[str] = mapped_column(String(32), nullable=False)
    geocoder_place_id: Mapped[str | None] = mapped_column(String(255))

    status: Mapped[DiscoveryStatus] = mapped_column(
        _enum(DiscoveryStatus, "discovery_status"), nullable=False, default=DiscoveryStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    club_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CityAlias(Base):
    """Normalized user input ("austin|tx|us") → canonical city, to avoid re-geocoding."""

    __tablename__ = "city_aliases"

    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    city_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cities.id", ondelete="CASCADE"), nullable=False
    )


class PostalCode(Base):
    """Geocoded postal code (cached): a focus point for sorting nearby courts."""

    __tablename__ = "postal_codes"

    country_code: Mapped[str] = mapped_column(String(2), primary_key=True)
    postal_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    city_name: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    city_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cities.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Club(TimestampMixin, Base):
    """A place to play tennis: a club, a sports centre, or a group of public courts."""

    __tablename__ = "clubs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    city_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Stable identity across refreshes, e.g. "osm:way/123456".
    external_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[ClubKind] = mapped_column(_enum(ClubKind, "club_kind"), nullable=False)
    location: Mapped[WKBElement] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    address: Mapped[str | None] = mapped_column(String(300))
    website: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(64))
    court_count: Mapped[int | None] = mapped_column(Integer)
    surface: Mapped[str | None] = mapped_column(String(64))
    access: Mapped[str | None] = mapped_column(String(32))
    lit: Mapped[bool | None] = mapped_column(Boolean)
    email: Mapped[str | None] = mapped_column(String(254))
    # Where clients book a court at this venue (online booking page), when we found one.
    booking_url: Mapped[str | None] = mapped_column(String(500))
    website_source: Mapped[str | None] = mapped_column(String(16))  # osm | wikidata | search
    contacts_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contacts_status: Mapped[str | None] = mapped_column(String(32))
    # Source identifiers merged into this club, e.g. {"osm": [...], "geoapify": [...]}.
    sources: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # False when the latest discovery no longer found it (kept for partner links).
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_clubs_location", "location", postgresql_using="gist"),)


class UserClub(Base):
    """A user's courts: where a partner is willing to play, or where a player likes to play."""

    __tablename__ = "user_clubs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    club_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clubs.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
