"""The new methods of the Shikimori and AniList clients, with the HTTP layer replaced. No network."""

import asyncio

import pytest

from app.providers.anilist import AniListProvider
from app.providers.shikimori import ENTRY_QUERY, ShikimoriClient, ShikimoriError


def run(coro):
    return asyncio.run(coro)


class StubShikimori(ShikimoriClient):
    def __init__(self, answer):
        super().__init__()
        self.answer = answer
        self.sent = []

    async def _post(self, query, variables, retries=3):
        self.sent.append((query, variables))
        return self.answer


class StubAniList(AniListProvider):
    def __init__(self, answers):
        super().__init__()
        self.answers = list(answers)
        self.sent = []

    async def _post(self, query, variables):
        self.sent.append(variables)
        return self.answers.pop(0)


def test_entries_are_asked_for_by_id_with_their_relations():
    client = StubShikimori({"data": {"animes": [{"id": "1"}, {"id": "2"}]}})

    assert run(client.fetch_entries(["1", "2"])) == [{"id": "1"}, {"id": "2"}]
    assert client.sent == [(ENTRY_QUERY, {"ids": "1,2"})]
    assert "related" in ENTRY_QUERY and "relationKind" in ENTRY_QUERY


def test_a_failed_entries_request_raises_while_an_empty_answer_does_not():
    with pytest.raises(ShikimoriError):
        run(StubShikimori(None).fetch_entries(["1"]))
    assert run(StubShikimori({"data": {"animes": []}}).fetch_entries(["1"])) == []


def test_a_strict_search_raises_on_failure_and_the_default_search_hides_it():
    assert run(StubShikimori(None).search_anime("x")) == []
    with pytest.raises(ShikimoriError):
        run(StubShikimori(None).search_anime("x", strict=True))


def test_anilist_ids_come_back_by_mal_id_and_unknown_ones_are_missing():
    client = StubAniList([{"Page": {"media": [{"id": 113415, "idMal": 40748}, {"id": 209895, "idMal": 63824}]}}])

    assert run(client.get_anilist_ids([63824, 40748, 99999999, 40748])) == {40748: 113415, 63824: 209895}
    assert client.sent == [{"ids": [40748, 63824, 99999999]}]  # sorted, each once, in one request


def test_anilist_ids_are_asked_for_in_pages_of_fifty():
    client = StubAniList([{"Page": {"media": []}}, {"Page": {"media": []}}])

    run(client.get_anilist_ids(range(1, 52)))

    assert [len(sent["ids"]) for sent in client.sent] == [50, 1]


def test_anilist_failure_raises_instead_of_looking_like_no_ids():
    with pytest.raises(RuntimeError):
        run(StubAniList([None]).get_anilist_ids([1]))


def test_schedules_are_asked_for_by_anilist_id_in_one_request():
    media = [{"id": 195516, "status": "RELEASING", "episodes": 12, "nextAiringEpisode": {"episode": 5, "airingAt": 1793368800}}]
    client = StubAniList([{"Page": {"media": media}}])

    assert run(client.get_schedules([200927, 195516, 195516])) == media
    assert client.sent == [{"ids": [195516, 200927]}]
    assert "nextAiringEpisode" in client.SCHEDULES_QUERY


def test_an_empty_schedule_answer_is_a_list_but_a_failed_one_raises():
    assert run(StubAniList([{"Page": {"media": []}}]).get_schedules([1])) == []
    with pytest.raises(RuntimeError):
        run(StubAniList([None]).get_schedules([1]))


def test_no_ids_means_no_schedule_request():
    client = StubAniList([])

    assert run(client.get_schedules([])) == []
    assert client.sent == []


def test_no_mal_ids_means_no_request():
    client = StubAniList([])

    assert run(client.get_anilist_ids([])) == {}
    assert client.sent == []
