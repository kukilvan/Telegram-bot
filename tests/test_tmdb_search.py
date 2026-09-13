"""Quick manual test for TMDbProvider.search_movie."""

import asyncio


async def main() -> None:
    from app.providers.tmdb import TMDbProvider

    provider = TMDbProvider()
    try:
        results = await provider.search_movie("Dune")
        print(f"Got {len(results)} movie results for 'Dune'")
        for r in results[:3]:
            # ASCII-safe fields only (id + year) to avoid cp1252 console issues.
            year = (r.get("first_air_date") or "")[:4]
            print(f"  - id={r['id']} year={year}")
    finally:
        await provider.aclose()


if __name__ == "__main__":
    asyncio.run(main())
