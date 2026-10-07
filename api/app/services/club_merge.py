"""Turn raw OSM/Geoapify places into deduplicated tennis sites.

OpenStreetMap usually maps each court as its own `leisure=pitch`, so a park with eight courts
is eight elements. Clients care about *places*, so we:
  1. merge records describing the same OSM element across sources,
  2. attach courts to the club / sports centre they sit in (nearest facility within reach,
     extended through adjacent courts for large venues),
  3. cluster the remaining courts into public court sites,
  4. collapse duplicate facilities (close together with similar names),
  5. name unnamed sites after the nearest park/school/campus, else their neighbourhood.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.integrations.geo import RawPlace
from app.models import ClubKind

COURT_TO_FACILITY_M = 200.0
COURT_CLUSTER_M = 80.0
DUPLICATE_FACILITY_M = 75.0
# Landmarks arrive pre-filtered to those whose outline is within 200 m of a court, but we
# compare against their *centre*, so allow for the size of a park or campus.
LANDMARK_M = 600.0
NEIGHBOURHOOD_M = 2500.0
NAME_SIMILARITY = 0.8
GENERIC_COURT_NAME = re.compile(r"^\s*(tennis\s*)?(court|cancha|platz)?\s*#?\d+\s*$", re.I)
FACILITY_LEISURE = {"sports_centre", "sports_hall", "stadium", "club"}


@dataclass
class Site:
    name: str
    kind: ClubKind
    lat: float
    lon: float
    external_key: str
    address: str | None = None
    website: str | None = None
    phone: str | None = None
    court_count: int | None = None
    surface: str | None = None
    access: str | None = None
    lit: bool | None = None
    sources: dict[str, list[str]] = field(default_factory=dict)


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class _Record:
    """One real-world element, possibly reported by several sources."""

    places: list[RawPlace]

    @property
    def primary(self) -> RawPlace:
        return next((p for p in self.places if p.source == "osm"), self.places[0])

    @property
    def name(self) -> str | None:
        return next((p.name for p in self.places if p.name), None)

    @property
    def tags(self) -> dict[str, str]:
        merged: dict[str, str] = {}
        for place in reversed(self.places):  # OSM tags win
            merged.update(place.tags)
        return merged

    @property
    def address(self) -> str | None:
        return next((p.address for p in self.places if p.address), None)

    @property
    def key(self) -> str:
        return f"{self.primary.source}:{self.primary.source_id}"

    def is_facility(self) -> bool:
        tags = self.tags
        return tags.get("leisure") in FACILITY_LEISURE or "club" in tags

    def is_generic_court(self) -> bool:
        return not self.name or bool(GENERIC_COURT_NAME.match(self.name))


def _merge_sources(places: list[RawPlace]) -> list[_Record]:
    by_ref: dict[str, _Record] = {}
    records: list[_Record] = []
    for place in sorted(places, key=lambda p: p.source != "osm"):  # OSM first
        if place.osm_ref and place.osm_ref in by_ref:
            by_ref[place.osm_ref].places.append(place)
            continue
        record = _Record([place])
        records.append(record)
        if place.osm_ref:
            by_ref[place.osm_ref] = record
    return records


def _courts_in(record: _Record) -> int:
    try:
        return max(1, int(record.tags.get("courts", "1")))
    except ValueError:
        return 1


def _cluster(records: list[_Record], radius_m: float) -> list[list[_Record]]:
    """Single-linkage clustering of courts by distance."""
    clusters: list[list[_Record]] = []
    for record in records:
        p = record.primary
        touching = [
            c
            for c in clusters
            if any(distance_m(p.lat, p.lon, o.primary.lat, o.primary.lon) <= radius_m for o in c)
        ]
        merged = [record]
        for cluster in touching:
            merged.extend(cluster)
            clusters.remove(cluster)
        clusters.append(merged)
    return clusters


def _similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= NAME_SIMILARITY


def _site_from(records: list[_Record], kind: ClubKind, name: str) -> Site:
    anchor = min(records, key=lambda r: r.key)
    lat = sum(r.primary.lat for r in records) / len(records)
    lon = sum(r.primary.lon for r in records) / len(records)
    tags = [r.tags for r in records]
    surfaces = Counter(t["surface"] for t in tags if t.get("surface"))
    lit_values = [t["lit"] == "yes" for t in tags if t.get("lit") in {"yes", "no"}]
    sources: dict[str, list[str]] = {}
    for record in records:
        for place in record.places:
            sources.setdefault(place.source, []).append(place.source_id)
    return Site(
        name=name,
        kind=kind,
        lat=lat,
        lon=lon,
        external_key=anchor.key,
        address=next((r.address for r in records if r.address), None),
        website=next(
            (
                t.get("website") or t.get("contact:website")
                for t in tags
                if t.get("website") or t.get("contact:website")
            ),
            None,
        ),
        phone=next(
            (
                t.get("phone") or t.get("contact:phone")
                for t in tags
                if t.get("phone") or t.get("contact:phone")
            ),
            None,
        ),
        surface=surfaces.most_common(1)[0][0] if surfaces else None,
        access=next((t["access"] for t in tags if t.get("access")), None),
        lit=any(lit_values) if lit_values else None,
        sources={k: sorted(set(v)) for k, v in sources.items()},
    )


def _nearest(lat: float, lon: float, places: list[RawPlace], max_m: float) -> str | None:
    best = min(
        ((distance_m(lat, lon, p.lat, p.lon), p.name) for p in places if p.name),
        default=None,
    )
    return best[1] if best and best[0] <= max_m else None


class _Namer:
    """Names unnamed sites after a nearby park/school, else their neighbourhood."""

    def __init__(self, landmarks: list[RawPlace]) -> None:
        self.venues = [p for p in landmarks if "place" not in p.tags]
        self.neighbourhoods = [p for p in landmarks if "place" in p.tags]

    def courts_name(self, lat: float, lon: float) -> str:
        venue = _nearest(lat, lon, self.venues, LANDMARK_M)
        if venue:
            return venue if "tennis" in venue.lower() else f"{venue} tennis courts"
        area = _nearest(lat, lon, self.neighbourhoods, NEIGHBOURHOOD_M)
        return f"Tennis courts · {area}" if area else "Tennis courts"


def build_sites(places: list[RawPlace]) -> list[Site]:
    namer = _Namer([p for p in places if p.landmark])
    records = _merge_sources([p for p in places if not p.landmark])
    facilities = [r for r in records if r.is_facility()]
    courts = [r for r in records if not r.is_facility()]

    # 1. Collapse duplicate facilities (e.g. a club mapped both as a node and as an area).
    groups: list[list[_Record]] = []
    for facility in facilities:
        p = facility.primary
        match = next(
            (
                g
                for g in groups
                if distance_m(p.lat, p.lon, g[0].primary.lat, g[0].primary.lon)
                <= DUPLICATE_FACILITY_M
                and _similar(facility.name or "", g[0].name or "")
            ),
            None,
        )
        if match:
            match.append(facility)
        else:
            groups.append([facility])

    # 2. Attach courts to the nearest facility within reach.
    attached: dict[int, list[_Record]] = {i: [] for i in range(len(groups))}
    loose: list[_Record] = []
    for court in courts:
        p = court.primary
        nearest = min(
            (
                (distance_m(p.lat, p.lon, g[0].primary.lat, g[0].primary.lon), i)
                for i, g in enumerate(groups)
            ),
            default=None,
        )
        if nearest and nearest[0] <= COURT_TO_FACILITY_M:
            attached[nearest[1]].append(court)
        else:
            loose.append(court)

    # Large venues: a court next to a venue's courts belongs to the venue, even if it's
    # farther than COURT_TO_FACILITY_M from the venue's own point.
    changed = True
    while changed and loose:
        changed = False
        for court in loose[:]:
            p = court.primary
            for members in attached.values():
                if any(
                    distance_m(p.lat, p.lon, m.primary.lat, m.primary.lon) <= COURT_CLUSTER_M
                    for m in members
                ):
                    members.append(court)
                    loose.remove(court)
                    changed = True
                    break

    sites = []
    for i, group in enumerate(groups):
        lead = group[0]
        tags = lead.tags
        kind = (
            ClubKind.CLUB
            if "club" in tags or tags.get("leisure") == "club"
            else ClubKind.SPORTS_CENTRE
        )
        site = _site_from(
            group, kind, lead.name or namer.courts_name(lead.primary.lat, lead.primary.lon)
        )
        # The facility's own position is more meaningful than the average with its courts.
        site.lat, site.lon = lead.primary.lat, lead.primary.lon
        court_total = sum(_courts_in(c) for c in attached[i])
        if court_total:
            court_site = _site_from(attached[i], kind, site.name)
            site.court_count = court_total
            site.surface = site.surface or court_site.surface
            site.lit = site.lit if site.lit is not None else court_site.lit
            for source, ids in court_site.sources.items():
                site.sources[source] = sorted(set(site.sources.get(source, [])) | set(ids))
        sites.append(site)

    # 3. Remaining courts become public court sites.
    for cluster in _cluster(loose, COURT_CLUSTER_M):
        named = next((r.name for r in cluster if not r.is_generic_court()), None)
        site = _site_from(cluster, ClubKind.PUBLIC_COURTS, named or "Tennis courts")
        if not named:
            site.name = namer.courts_name(site.lat, site.lon)
        site.court_count = sum(_courts_in(r) for r in cluster)
        sites.append(site)

    return sorted(sites, key=lambda s: s.name.lower())
