"""The approximate premiere of an anime season or part (spec 3 and 4 of stage 9.1d, KI-81): the date in words, what
Shikimori says (the saved answer of 2026-11-22), the stub that has no moment, what it does to what is stored, the day
announced after it, and how it reads in the card, the message, the Feed and the export. Pure rules, no database
(the storage round trip and the polls are `test_tracker_anime_approximate_polls`)."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from app.tracker import cards, export_all, feed_rows, series_events, series_messages
from app.tracker.anime_events import assemble, flavor
from app.tracker.dedup import moved_key
from app.tracker.feed_rows import FeedTitle
from app.tracker.models import EpisodeRecord, EpisodeTiming, TitleKind
from app.tracker.movie_events import INTERVAL_WAITING
from app.tracker.release_dates import NOT_ANNOUNCED, ReleaseDate
from app.tracker.seasons import ANNOUNCED, Episode, PartCut, Season, SeasonAnnouncement, summarize
from app.tracker.sources.anilist_schedule import PartSchedule
from app.tracker.sources.shikimori_chain import SeasonPart, SourceIds, parse_entry, part_episodes

FIXTURE = Path(__file__).parent / "fixtures" / "shikimori" / "premiere_precision.json"
EXACT, DAY, UNKNOWN, MONTH, YEAR = (
    EpisodeTiming.EXACT, EpisodeTiming.DAY, EpisodeTiming.UNKNOWN, EpisodeTiming.MONTH, EpisodeTiming.YEAR
)
JANUARY = ReleaseDate(2027, 1)
IN_2027 = ReleaseDate(2027)
NOW = datetime(2026, 11, 23, 12, 0)
ANIME = flavor(None)


# --- the date in words (spec 3) -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "when, label, phrase",
    [
        (ReleaseDate(2027, 2, 12), "12 февраля 2027", "12 февраля 2027"),
        (ReleaseDate(2027, 1), "январь 2027", "в январе 2027"),
        (ReleaseDate(2027, 5), "май 2027", "в мае 2027"),
        (ReleaseDate(2027, quarter=4), "4 квартал 2027", "в 4 квартале 2027"),
        (ReleaseDate(2027, quarter=2), "2 квартал 2027", "во 2 квартале 2027"),
        (ReleaseDate(2027, quarter=1), "1 квартал 2027", "в 1 квартале 2027"),
        (ReleaseDate(2028), "2028", "в 2028"),
        (NOT_ANNOUNCED, "дата не объявлена", "дата не объявлена"),
    ],
)
def test_a_date_reads_alone_and_inside_a_sentence(when, label, phrase):
    assert (when.label, when.phrase) == (label, phrase)


def test_every_month_has_its_prepositional_case():
    words = [ReleaseDate(2027, month).phrase.split()[1] for month in range(1, 13)]

    assert words == [
        "январе", "феврале", "марте", "апреле", "мае", "июне", "июле", "августе", "сентябре", "октябре", "ноябре", "декабре"
    ]


def test_a_period_is_made_from_its_first_day_and_its_timing():
    assert ReleaseDate.of_period(date(2027, 4, 1), MONTH) == ReleaseDate(2027, 4)
    assert ReleaseDate.of_period(date(2027, 1, 1), YEAR) == IN_2027
    assert ReleaseDate.of_day(date(2027, 1, 9)) == ReleaseDate(2027, 1, 9)
    assert (ReleaseDate(2027, 4).timing, IN_2027.timing) == (MONTH, YEAR)
    with pytest.raises(ValueError):
        ReleaseDate.of_period(date(2027, 1, 1), DAY)


# --- what Shikimori says (spec 4.1) ----------------------------------------------------------------------------------


def saved_entries():
    return {raw["id"]: parse_entry(raw) for raw in json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]["animes"]}


def test_the_saved_answer_gives_a_month_or_the_year_alone():
    entries = saved_entries()

    assert entries["62841"].aired == ReleaseDate(2027, 4)  # «Монолог фармацевта», season 3 part 2
    assert entries["63193"].aired == JANUARY  # «Ванпанчмен», season 3 part 2
    assert entries["65077"].aired == IN_2027  # «Реинкарнация безработного», season 3 part 2: the year alone
    assert entries["65077"].aired_on == date(2027, 1, 1)  # the order of the chain still reads the day of `date`


@pytest.mark.parametrize(
    "aired_on, expected",
    [
        ({"date": "2027-01-09", "year": 2027, "month": 1, "day": 9}, ReleaseDate(2027, 1, 9)),
        ({"date": "2027-02-01", "year": 2027, "month": 2, "day": 30}, ReleaseDate(2027, 2)),  # no such day
        ({"date": "2027-02-01", "year": 2027, "month": 2, "day": "9"}, ReleaseDate(2027, 2)),  # not a number
        ({"date": "2027-01-01", "year": 2027, "month": 13, "day": 1}, IN_2027),  # a bad month
        ({"date": "2027-01-01", "year": 2027, "month": None, "day": 5}, IN_2027),  # a day but no month
        ({"date": "2027-01-01", "year": None, "month": 1, "day": 1}, NOT_ANNOUNCED),  # no year
        ({"date": None, "year": None, "month": None, "day": None}, NOT_ANNOUNCED),
        (None, NOT_ANNOUNCED),
        ("2027", NOT_ANNOUNCED),
        ({"date": "2026-11-20", "year": 2026}, ReleaseDate(2026, 11, 20)),  # the shape of the answers saved before
    ],
)
def test_garbage_falls_to_what_is_sure(aired_on, expected):
    assert ReleaseDate.from_shikimori(aired_on) == expected


# --- the stub (spec 4.2) ---------------------------------------------------------------------------------------------


def entry(aired_on, out=0, status="anons", next_at=None):
    return parse_entry({
        "id": "1", "name": "Show Part 2", "kind": "tv", "status": status, "episodes": 12, "episodesAired": out,
        "nextEpisodeAt": next_at, "airedOn": aired_on, "releasedOn": {"date": None},
    })


def test_an_announced_entry_gets_the_stub_of_its_precision():
    by_day = part_episodes(entry({"date": "2027-01-09", "year": 2027, "month": 1, "day": 9}), 13)
    by_month = part_episodes(entry({"date": "2027-01-01", "year": 2027, "month": 1, "day": None}), 13)
    by_year = part_episodes(entry({"date": "2027-01-01", "year": 2027, "month": None, "day": None}), 13)
    unknown = part_episodes(entry({"date": None, "year": None, "month": None, "day": None}), 13)

    assert by_day == [Episode(13, datetime(2027, 1, 9), DAY)]
    assert by_month == [Episode(13, None, MONTH, JANUARY)]
    assert by_year == [Episode(13, None, YEAR, IN_2027)]
    assert unknown == []


def test_a_next_moment_beats_the_stub():
    listed = part_episodes(entry({"date": "2027-01-01", "year": 2027, "month": 1, "day": None}, next_at="2027-01-09T18:00:00+03:00"), 13)

    assert listed == [Episode(13, datetime(2027, 1, 9, 15, 0), EXACT)]


def test_the_episodes_out_of_an_entry_known_by_the_month_are_all_unknown():
    listed = part_episodes(entry({"date": "2026-10-01", "year": 2026, "month": 10, "day": None}, out=3, status="ongoing"), 1)

    assert [e.timing for e in listed] == [UNKNOWN, UNKNOWN, UNKNOWN]
    assert all(e.air_at == datetime(2026, 10, 1) for e in listed)


def stubbed(stub=Episode(13, None, MONTH, JANUARY)):
    """Season 3: part 1 out in full in summer, part 2 known by the stub."""
    out = tuple(Episode(n, datetime(2026, 7, 6) + timedelta(weeks=n - 1), EXACT) for n in range(1, 13))
    return Season(3, "Сезон 3", 24, out + (stub,), (PartCut(1, 12, "100"), PartCut(13, 12, "101")), "100")


def announced(stub=Episode(1, None, MONTH, JANUARY)):
    return Season(4, "Сезон 4", 12, (stub,), (PartCut(1, 12, "200"),), "200")


@pytest.mark.parametrize("now", [datetime(2027, 1, 1), datetime(2027, 1, 1, 12, 0), datetime(2027, 3, 5)])
def test_the_stub_is_never_out_whatever_the_clock(now):
    season = announced()
    second = stubbed().parts()[1]

    assert season.released(now) == 0 and season.status(now) == ANNOUNCED
    assert second.released(now) == 0 and second.next_episode(now) is None
    assert season.first_episode() is None and season.premiere() == Episode(1, None, MONTH, JANUARY)


def test_the_stub_gives_no_event_and_no_hurry():
    old = series_events.ShowState((announced(),))

    events = series_events.detect_events(1, "Аниме", old, old, datetime(2026, 12, 31), datetime(2027, 1, 2), flavor=ANIME)

    assert events == []
    assert series_events.check_interval(old, datetime(2026, 12, 31, 23, 0)) == INTERVAL_WAITING


# --- what it does to what is stored, and the day after it (spec 4.3, 4.4) --------------------------------------------


def test_a_fresh_stub_replaces_a_stored_made_up_day_with_no_message():
    old = series_events.ShowState((stubbed(Episode(13, datetime(2027, 1, 1), DAY)),))
    fresh = series_events.ShowState((stubbed(),))

    new = fresh.keeping_known(old)

    assert new.seasons[0].episodes[-1] == Episode(13, None, MONTH, JANUARY)
    assert series_events.detect_events(1, "Аниме", old, new, NOW - timedelta(days=1), NOW, flavor=ANIME) == []


def test_a_gap_still_keeps_what_was_stored():
    old = series_events.ShowState((stubbed(Episode(13, datetime(2027, 1, 9), DAY)),))
    fresh = series_events.ShowState((stubbed(Episode(13, None)),))

    assert fresh.keeping_known(old).seasons[0].episodes[-1] == Episode(13, datetime(2027, 1, 9), DAY)


def announcement(old_stub, new_episode, observed_at=NOW - timedelta(days=1)):
    old = series_events.ShowState((stubbed(old_stub),))
    new = series_events.ShowState((stubbed(new_episode),)).keeping_known(old)
    [event] = series_events.detect_events(1, "Аниме", old, new, observed_at, NOW, flavor=ANIME)
    return event


def test_the_exact_day_after_an_approximate_one_is_announced_under_the_key_of_that_look():
    observed_at = datetime(2026, 11, 22, 9, 30, 15)

    event = announcement(Episode(13, None, MONTH, JANUARY), Episode(13, datetime(2027, 1, 9), DAY), observed_at)

    assert event.type == series_events.DATE_ANNOUNCED
    assert event.dedup_key == moved_key("anime:1:src100:p2:date_announced", observed_at)
    assert event.text.endswith("объявлена дата части 2 сезона 3\nПремьера: 9 января 2027")


def test_a_first_day_with_no_approximate_one_before_keeps_the_plain_key():
    event = announcement(Episode(13, None), Episode(13, datetime(2027, 1, 9), DAY))

    assert event.dedup_key == "anime:1:src100:p2:date_announced"


def test_the_season_announced_after_its_year_has_the_key_of_that_look_too():
    observed_at = NOW - timedelta(days=1)
    old = series_events.ShowState((announced(Episode(1, None, YEAR, IN_2027)),))
    new = series_events.ShowState((announced(Episode(1, datetime(2027, 4, 9), DAY)),)).keeping_known(old)

    [event] = series_events.detect_events(1, "Аниме", old, new, observed_at, NOW, flavor=ANIME)

    assert event.dedup_key == moved_key("anime:1:src200:date_announced", observed_at)


def test_an_anilist_moment_beats_the_stub_of_a_part_and_is_announced():
    part = SeasonPart(3, 2, 13, 12, SourceIds("101", "101", "301"), "anons")
    first = SeasonPart(3, 1, 1, 12, SourceIds("100", "100", "300"), "released")
    stored = stubbed()
    schedule = PartSchedule("NOT_YET_RELEASED", 0, 1, datetime(2027, 1, 9, 15, 0))
    observed_at = NOW - timedelta(days=1)

    [season] = assemble([stubbed()], [first, part], {"101": schedule}, [stored], NOW, {"101"}, (), observed_at).seasons
    old = series_events.ShowState((stored,))
    new = series_events.ShowState((season,)).keeping_known(old)
    [event] = series_events.detect_events(1, "Аниме", old, new, observed_at, NOW, flavor=ANIME)

    assert season.episodes[-1] == Episode(13, datetime(2027, 1, 9, 15, 0), EXACT)
    assert event.dedup_key == moved_key("anime:1:src100:p2:date_announced", observed_at)


# --- how it reads (spec 4.5) -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("stub, words", [(Episode(13, None, MONTH, JANUARY), "в январе 2027"), (Episode(13, None, YEAR, IN_2027), "в 2027")])
def test_the_card_and_the_end_of_a_part_name_the_approximate_start(stub, words):
    season = stubbed(stub)
    view = summarize([season], (), datetime(2026, 12, 30))
    first, second = season.parts()

    assert cards.progress_line(view.current) == f"Сезон 3, часть 1: вышло 12 из 12; часть 2 — {words}"
    assert series_messages.message_part_ended("Аниме", first, 12, second, ANIME).endswith(f"часть 2 — {words}")


def test_a_dated_start_still_reads_from_its_day():
    season = stubbed(Episode(13, datetime(2027, 1, 9), DAY))

    assert cards.progress_line(summarize([season], (), datetime(2026, 12, 30)).current).endswith("часть 2 — с 9 января")


@pytest.mark.parametrize("stub, words", [(Episode(1, None, MONTH, JANUARY), "в январе 2027"), (Episode(1, None, YEAR, IN_2027), "в 2027")])
def test_an_announced_season_names_its_approximate_premiere(stub, words):
    assert cards.announced_line(SeasonAnnouncement(4, stub)) == f"Сезон 4 анонсирован, премьера {words}"
    assert summarize([announced(stub)], (), NOW).announced.premiere == stub


TITLE = FeedTitle(7, TitleKind.ANIME, "Ванпанчмен")


def test_the_feed_puts_the_approximate_premiere_in_later_on_the_last_day_of_its_period():
    pieces = feed_rows.season_pieces(TITLE, [stubbed()], timedelta(weeks=6), None, date(2026, 12, 30))

    soon, later = feed_rows.upcoming(pieces, date(2026, 12, 30))

    assert [(p.day, p.when, p.text) for p in pieces] == [(date(2027, 1, 31), "январь 2027", "Сезон 3, часть 2 — премьера")]
    assert soon == () and [(r.day, r.when) for r in later] == [(date(2027, 1, 31), "январь 2027")]


def test_the_feed_drops_the_piece_once_its_period_has_passed():
    year = stubbed(Episode(13, None, YEAR, IN_2027))

    assert feed_rows.season_pieces(TITLE, [stubbed()], timedelta(weeks=6), None, date(2027, 2, 1)) == []
    assert [p.when for p in feed_rows.season_pieces(TITLE, [year], timedelta(weeks=6), None, date(2027, 12, 31))] == ["2027"]


def test_the_export_gives_the_period_and_no_moment():
    month = EpisodeRecord(number=13, air_at=datetime(2027, 1, 1), timing=MONTH)
    year = EpisodeRecord(number=13, air_at=datetime(2027, 1, 1), timing=YEAR)

    assert export_all._episode(month, None) == {"number": 13, "air_at": None, "approximate": "2027-01"}
    assert export_all._episode(year, None) == {"number": 13, "air_at": None, "approximate": "2027"}
