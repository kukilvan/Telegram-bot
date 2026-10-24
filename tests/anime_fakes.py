"""Stand-ins for the Shikimori and AniList clients, serving the saved real answers (tests/fixtures/shikimori)."""

import json
import pathlib

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "shikimori"
FRANCHISES = ("one_piece.json", "jujutsu_kaisen.json", "kusuriya.json", "made_in_abyss.json")


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["data"]["animes"]


class FakeShikimori:
    """Serves the saved entries by id, like `animes(ids: ...)`; an id it does not hold is simply missing."""

    def __init__(self, *fixtures):
        self.by_id = {a["id"]: a for name in (fixtures or FRANCHISES) for a in load(name)}
        self.fetched = []
        self.broken = False

    async def fetch_entries(self, ids):
        self.fetched.append(list(ids))
        if self.broken:
            raise ConnectionError("Shikimori is down")
        return [self.by_id[i] for i in ids if i in self.by_id]

    async def search_anime(self, query, strict=False):
        if self.broken and strict:
            raise ConnectionError("Shikimori is down")
        return load("search_jujutsu.json")


class FakeAniList:
    def __init__(self, ids=None):
        self.ids = ids
        self.asked = []
        self.broken = False

    async def get_anilist_ids(self, mal_ids):
        self.asked.append(sorted(mal_ids))
        if self.broken:
            raise ConnectionError("AniList is down")
        if self.ids is not None:
            return {m: a for m, a in self.ids.items() if m in mal_ids}
        return {m: m + 100000 for m in mal_ids}  # every MAL id has its own AniList id
