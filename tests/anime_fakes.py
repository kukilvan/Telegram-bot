"""Stand-ins for the Shikimori and AniList clients, serving the saved real answers (tests/fixtures/shikimori)."""

import json
import pathlib
from datetime import timezone

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


# MAL id -> AniList id of the entries in tests/fixtures/anilist/schedules.json (the saved real answer)
REAL_ANILIST_IDS = {21: 21, 34599: 97986, 40748: 113415, 54492: 161645, 58514: 176301, 61987: 195516, 62841: 200927, 63824: 209895}
ANILIST_FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "anilist"


class FakeAniList:
    """Ids by MAL id, and the airing schedules by AniList id (raw records, as AniList sends them)."""

    def __init__(self, ids=None, schedules=None):
        self.ids = ids
        self.schedules = dict(schedules or {})
        self.asked = []
        self.asked_schedules = []
        self.broken = False  # AniList is down: every request fails
        self.schedules_broken = False  # only the schedule request fails

    async def get_anilist_ids(self, mal_ids):
        self.asked.append(sorted(mal_ids))
        if self.broken:
            raise ConnectionError("AniList is down")
        if self.ids is not None:
            return {m: a for m, a in self.ids.items() if m in mal_ids}
        return {m: m + 100000 for m in mal_ids}  # every MAL id has its own AniList id

    async def get_schedules(self, anilist_ids):
        self.asked_schedules.append(sorted(anilist_ids))
        if self.broken or self.schedules_broken:
            raise ConnectionError("AniList is down")
        return [dict(self.schedules[i]) for i in anilist_ids if i in self.schedules]

    # --- what a test changes in AniList's answer ---

    def next_episode(self, anilist_id, episode, moment):
        """The entry is running; `episode` (its own number) comes out at `moment` (naive UTC)."""
        record = self.schedules[anilist_id]
        record["status"] = "RELEASING"
        record["nextAiringEpisode"] = {"episode": episode, "airingAt": int(moment.replace(tzinfo=timezone.utc).timestamp())}

    def finish(self, anilist_id, episodes):
        record = self.schedules[anilist_id]
        record.update(status="FINISHED", episodes=episodes, nextAiringEpisode=None)


def real_anilist(without=()):
    """AniList as it answered when the fixtures were saved; `without` are MAL ids it knows nothing about."""
    saved = json.loads((ANILIST_FIXTURES / "schedules.json").read_text(encoding="utf-8"))["data"]["Page"]["media"]
    ids = {mal: anilist for mal, anilist in REAL_ANILIST_IDS.items() if mal not in without}
    return FakeAniList(ids=ids, schedules={m["id"]: m for m in saved if m["id"] in ids.values()})
