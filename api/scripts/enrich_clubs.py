"""Find websites, phones and court-booking links for clubs already in the database.

  docker compose exec api python -m scripts.enrich_clubs            # every city
  docker compose exec api python -m scripts.enrich_clubs --city Austin
  docker compose exec api python -m scripts.enrich_clubs --city Austin --force   # re-check all

Runs the same batches as the worker, inline. New cities are enriched automatically after
discovery, so this is for backfills.
"""

import argparse
import asyncio

from sqlalchemy import func, select, update

from app.core.db import get_sessionmaker
from app.integrations.geo import get_overpass
from app.integrations.websites import get_website_search
from app.models import City, Club, ClubKind
from app.services.club_enrichment import enrich_batch


async def main(city_name: str | None, force: bool) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        query = select(City)
        if city_name:
            query = query.where(func.lower(City.name) == city_name.lower())
        cities = list(await session.scalars(query.order_by(City.name)))
    if not cities:
        print("No matching cities.")
        return
    if force:
        async with sessionmaker() as session, session.begin():
            await session.execute(
                update(Club)
                .where(Club.city_id.in_([c.id for c in cities]))
                .values(contacts_checked_at=None)
            )
    search = get_website_search()
    print("Web search:", "Brave" if search else "off (set BRAVE_SEARCH_API_KEY to enable)")

    for city in cities:
        while True:
            async with sessionmaker() as session, session.begin():
                checked = await enrich_batch(session, city.id, get_overpass(), search)
            if not checked:
                break
            print(f"  {city.name}: checked {checked} clubs")
        async with sessionmaker() as session:
            rows = (
                await session.execute(
                    select(
                        Club.kind,
                        func.count(),
                        func.count(Club.website),
                        func.count(Club.phone),
                        func.count(Club.booking_url),
                    )
                    .where(Club.city_id == city.id, Club.active.is_(True))
                    .group_by(Club.kind)
                )
            ).all()
        for kind, total, websites, phones, booking in rows:
            label = "public courts" if kind is ClubKind.PUBLIC_COURTS else kind.value
            print(
                f"{city.name:>10} | {label:<14} | {total:>4} total | {websites:>3} website"
                f" | {phones:>3} phone | {booking:>3} booking link"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--city")
    parser.add_argument("--force", action="store_true", help="re-check clubs checked recently")
    args = parser.parse_args()
    asyncio.run(main(args.city, args.force))
