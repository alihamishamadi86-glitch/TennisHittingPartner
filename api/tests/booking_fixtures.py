"""Shared booking test setup (registered in conftest): a bookable client, Austin clubs and an
approved partner available 08:00–12:00 every day."""

import pytest

from tests.test_availability_api import club_ids, make_partner
from tests.test_bookings_api import ready_client


@pytest.fixture
async def setup(make_client, geocoder, sources, deliver):  # type: ignore[no-untyped-def]
    client = await ready_client(make_client)
    downtown, north = await club_ids(client, deliver)
    partner, partner_id = await make_partner(
        make_client,
        [downtown],
        schedule=[{"weekday": d, "start": "08:00", "end": "12:00"} for d in range(7)],
    )
    await deliver()
    return client, partner, partner_id, downtown, north
