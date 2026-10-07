import random

from app.integrations.geo import RawPlace
from app.models import ClubKind
from app.services.club_merge import build_sites, distance_m

# ~0.0001° latitude ≈ 11 m
BASE_LAT, BASE_LON = 30.2672, -97.7431


def court(osm_id: int, dlat: float = 0, dlon: float = 0, **tags: str) -> RawPlace:
    ref = f"way/{osm_id}"
    return RawPlace(
        source="osm",
        source_id=ref,
        name=tags.pop("name", None),
        lat=BASE_LAT + dlat,
        lon=BASE_LON + dlon,
        tags={"leisure": "pitch", "sport": "tennis", **tags},
        osm_ref=ref,
    )


def facility(osm_id: int, name: str, dlat: float = 0, dlon: float = 0, **tags: str) -> RawPlace:
    ref = f"way/{osm_id}"
    return RawPlace(
        source="osm",
        source_id=ref,
        name=name,
        lat=BASE_LAT + dlat,
        lon=BASE_LON + dlon,
        tags={"leisure": "sports_centre", "sport": "tennis", "name": name, **tags},
        osm_ref=ref,
    )


def test_adjacent_public_courts_become_one_site() -> None:
    park = [court(i, dlat=0.0002 * i, surface="hard", lit="yes") for i in range(1, 5)]
    far_away = court(99, dlat=0.05)

    sites = build_sites([*park, far_away])

    assert len(sites) == 2
    big = max(sites, key=lambda s: s.court_count or 0)
    assert big.kind is ClubKind.PUBLIC_COURTS
    assert big.court_count == 4
    assert big.name == "Tennis courts"
    assert big.surface == "hard"
    assert big.lit is True
    assert big.external_key == "osm:way/1"


def test_courts_attach_to_nearby_club() -> None:
    club = facility(500, "Westwood Tennis Club", club="sport", website="https://westwood.example")
    courts = [court(i, dlat=0.0003 * i, surface="clay" if i < 4 else "hard") for i in range(1, 7)]

    sites = build_sites([club, *courts])

    assert len(sites) == 1
    site = sites[0]
    assert site.name == "Westwood Tennis Club"
    assert site.kind is ClubKind.CLUB
    assert site.court_count == 6
    assert site.surface == "clay"
    assert site.website == "https://westwood.example"
    assert (site.lat, site.lon) == (BASE_LAT, BASE_LON)
    assert len(site.sources["osm"]) == 7


def test_far_court_is_not_attached_to_club() -> None:
    club = facility(500, "Westwood Tennis Club", club="sport")
    sites = build_sites([club, court(1, dlat=0.0001), court(2, dlat=0.01)])
    assert sorted((s.kind, s.court_count) for s in sites) == [
        (ClubKind.CLUB, 1),
        (ClubKind.PUBLIC_COURTS, 1),
    ]


def test_courts_tag_counts_multiple_courts() -> None:
    sites = build_sites([court(1, courts="3"), court(2, dlat=0.0002, courts="2")])
    assert sites[0].court_count == 5


def test_named_courts_keep_a_meaningful_name() -> None:
    sites = build_sites(
        [court(1, name="Court 1"), court(2, dlat=0.0002, name="Zilker Park Tennis Courts")]
    )
    assert sites[0].name == "Zilker Park Tennis Courts"


def test_geoapify_record_merges_with_osm_and_adds_address() -> None:
    osm = facility(700, "Austin Tennis Center")
    geoapify = RawPlace(
        source="geoapify",
        source_id="geo-abc",
        name="Austin Tennis Center",
        lat=BASE_LAT + 0.00001,
        lon=BASE_LON,
        tags={"sport": "tennis"},
        address="7800 Johnny Morris Rd, Austin, TX",
        osm_ref="way/700",
    )

    sites = build_sites([geoapify, osm])

    assert len(sites) == 1
    assert sites[0].address == "7800 Johnny Morris Rd, Austin, TX"
    assert sites[0].external_key == "osm:way/700"
    assert sites[0].sources == {"geoapify": ["geo-abc"], "osm": ["way/700"]}


def test_duplicate_facilities_collapse() -> None:
    area = facility(1, "Pharr Tennis Center")
    node = RawPlace(
        source="osm",
        source_id="node/2",
        name="Pharr Tennis Centre",
        lat=BASE_LAT + 0.0002,
        lon=BASE_LON,
        tags={"leisure": "sports_centre", "sport": "tennis"},
        osm_ref="node/2",
    )
    different = facility(3, "Caswell Tennis Center", dlat=0.0003)

    names = sorted(s.name for s in build_sites([area, node, different]))
    assert names == ["Caswell Tennis Center", "Pharr Tennis Center"]


def test_result_is_independent_of_input_order() -> None:
    places = [
        facility(10, "Club A", club="sport"),
        *[court(i, dlat=0.0002 * i) for i in range(11, 15)],
        *[court(i, dlat=0.03 + 0.0002 * i) for i in range(20, 23)],
    ]
    expected = {(s.external_key, s.court_count) for s in build_sites(places)}
    for seed in range(5):
        shuffled = places[:]
        random.Random(seed).shuffle(shuffled)
        assert {(s.external_key, s.court_count) for s in build_sites(shuffled)} == expected


def landmark(osm_id: int, name: str, dlat: float = 0, **tags: str) -> RawPlace:
    ref = f"way/{osm_id}"
    return RawPlace(
        source="osm",
        source_id=ref,
        name=name,
        lat=BASE_LAT + dlat,
        lon=BASE_LON,
        tags={"leisure": "park", "name": name, **tags},
        osm_ref=ref,
        landmark=True,
    )


def test_unnamed_courts_take_nearest_landmark_name() -> None:
    sites = build_sites(
        [
            court(1),
            court(2, dlat=0.0002),
            landmark(90, "Zilker Park", dlat=0.001),  # ~110 m
            landmark(91, "Far Away School", dlat=0.01),  # ~1.1 km
            court(3, dlat=0.05),  # nothing nearby
        ]
    )
    assert sorted(s.name for s in sites) == ["Tennis courts", "Zilker Park tennis courts"]


def test_landmark_names_already_mentioning_tennis_are_used_as_is() -> None:
    sites = build_sites([court(1), landmark(90, "Pease Park Tennis Area", dlat=0.0005)])
    assert sites[0].name == "Pease Park Tennis Area"


def test_neighbourhood_is_the_fallback_name() -> None:
    hyde_park = RawPlace(
        source="osm",
        source_id="node/77",
        name="Hyde Park",
        lat=BASE_LAT + 0.01,  # ~1.1 km: too far for a venue, fine for a neighbourhood
        lon=BASE_LON,
        tags={"place": "neighbourhood", "name": "Hyde Park"},
        landmark=True,
    )
    sites = build_sites([court(1), hyde_park])
    assert sites[0].name == "Tennis courts · Hyde Park"


def test_landmarks_alone_produce_no_sites() -> None:
    assert build_sites([landmark(90, "Zilker Park")]) == []


def test_distance() -> None:
    assert 10 < distance_m(BASE_LAT, BASE_LON, BASE_LAT + 0.0001, BASE_LON) < 12
