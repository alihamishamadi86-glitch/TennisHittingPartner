"""Promote an existing account to admin.

The person registers normally first, then:
  local:  docker compose run --rm api python -m scripts.create_admin you@example.com
  GCP:    gcloud run jobs execute thp-manage --region us-central1 --wait \
            --args=scripts.create_admin,you@example.com
"""

import argparse
import asyncio
import sys

from app.core.db import get_sessionmaker
from app.services.profiles import ProfileNotFoundError, promote_to_admin


async def main(email: str) -> int:
    async with get_sessionmaker()() as session:
        try:
            user = await promote_to_admin(session, email)
        except ProfileNotFoundError:
            print(f"No account found for {email}. Register first, then re-run.", file=sys.stderr)
            return 1
        await session.commit()
        print(f"{user.email} is now an admin.")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("email")
    sys.exit(asyncio.run(main(parser.parse_args().email)))
