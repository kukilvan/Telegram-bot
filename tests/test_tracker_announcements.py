"""The announcements of expansions and games of a series reach the owner (spec 6.4–6.6, 7.5, 7.6 of stage 6.3, ticket 04):
the buttons «Следить» and «Карточка» (`actions.FOLLOW_TYPES`), the names of the buttons in a summary, each announcement
a message or a line of its own, «Недавно» of the Feed with `Followable` / `FollowOffer`, the two samples of «Тестовое
событие», and an announcement that waits while the owner already follows its game.

Driven through the facade as in `test_tracker_game_follow_ups`: fake clock, made-up game source, fake follow-up source.
The rules are set as the owner has them: UTC, Sunday to Thursday are working days, the summary at 15:00; the tests
run on Mondays, so a message before 15:00 waits for the summary and one after it goes at once.
"""

import pytest

from app.tracker import actions, follow_ups, movie_events, price_events, sequel_events
from app.tracker.actions import FOLLOW, FOLLOW_TYPES, Action
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.feed_rows import FollowOffer, Followable
from app.tracker.models import TitleKind
from test_tracker_game_follow_ups import (
    T0, FakeClock, FakeFollowUps, MadeUpGames, add, follow_up, game, run, series,
)

CARD = "card"


class ActionSender:
    """Keeps the buttons too."""

    def __init__(self):
        self.sent = []

    async def send(self, message, actions=()):
        self.sent.append((message, list(actions)))


@pytest.fixture
def clock():
    return FakeClock(T0)


@pytest.fixture
def sender():
    return ActionSender()


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def igdb():
    return MadeUpGames()


@pytest.fixture
def follow():
    return FakeFollowUps()


@pytest.fixture
def tracker(session_factory, clock, sender, igdb, follow):
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={TitleKind.GAME: igdb}, follow_up_source=follow)
    run(tracker.set_delivery_rules(
        tz_name="UTC", workdays=[6, 0, 1, 2, 3], summary_at="15:00", quiet_from="23:00", quiet_until="07:30"
    ))
    return tracker


def announce(tracker, igdb, follow, clock, *, hours=0):
    """A game in the list, its reference point, then a week later an expansion and a game of the series: two queued
    announcements. `hours` moves the second check later in the day."""
    title_id = add(tracker, igdb, name="Elden Ring")
    run(tracker.poll_due())
    follow.answers["1"] = series(
        follow_up("2", "Elden Ring Nightreign"), expansions=[follow_up("3", "Elden Ring: Shadow of the Erdtree")]
    )
    clock.advance(days=7, hours=hours)
    run(tracker.poll_due())
    return title_id


# --- the buttons (6.4) -----------------------------------------------------------------------------------------------


def test_follow_types_are_the_movie_sequel_and_the_two_announcements_of_a_game():
    assert set(FOLLOW_TYPES) == {sequel_events.SEQUEL_ANNOUNCED, *follow_ups.TYPES}


@pytest.mark.parametrize("event_type", follow_ups.TYPES)
def test_a_game_announcement_has_follow_and_the_card_of_the_checked_game(event_type):
    data = {"kind": "game", "sequel_id": "3", "sequel_title": "Shadow of the Erdtree"}

    buttons = actions.event_actions(event_type, 11, 7, data)

    assert buttons == [Action("👀 Следить", FOLLOW, "game:3"), Action("📄 Карточка", CARD, 7)]


def test_a_movie_announcement_keeps_follow_alone():
    data = {"kind": "movie", "sequel_id": "9", "sequel_title": "Дюна: Часть третья"}

    assert actions.event_actions(sequel_events.SEQUEL_ANNOUNCED, 11, 7, data) == [Action("👀 Следить", FOLLOW, "movie:9")]


def test_an_announcement_that_names_nothing_falls_back_to_its_own_number():
    assert actions.event_actions(follow_ups.SEQUEL_ANNOUNCED, 11, 7, {})[0] == Action("👀 Следить", FOLLOW, 11)


@pytest.mark.parametrize(
    "event_type", [movie_events.RELEASED, price_events.TYPES[0], "test", "game_released", "episode_out"]
)
def test_nothing_outside_the_follow_types_offers_follow(event_type):
    assert event_type not in FOLLOW_TYPES
    assert FOLLOW not in {a.name for a in actions.event_actions(event_type, 1, 2, {"kind": "game", "sequel_id": "3"})}


# --- in a summary and outside it (6.5) -------------------------------------------------------------------------------


def test_in_a_summary_follow_is_named_by_the_announced_game_and_the_card_by_the_checked_one(
    tracker, igdb, follow, clock, sender
):
    announce(tracker, igdb, follow, clock)
    assert sender.sent == []  # a working morning: the announcements wait for the summary

    clock.advance(hours=3)  # 15:00
    run(tracker.deliver_pending())

    [(message, buttons)] = sender.sent
    lines = message.splitlines()
    assert "Сводка" in lines[0]
    assert sum("Анонсировано дополнение" in line for line in lines) == 1  # each announcement is a line of its own
    assert sum("Анонсирована новая игра серии" in line for line in lines) == 1
    assert [a.label for a in buttons] == [
        "👀 Следить: Elden Ring: Shadow of the Erdtree",  # the expansions go before the games of the series
        "👀 Следить: Elden Ring Nightreign",
        "📄 Карточка: Elden Ring",
    ]
    assert [a.arg for a in buttons if a.name == FOLLOW] == ["game:3", "game:2"]


def test_a_long_name_is_cut_on_the_card_button_but_never_on_follow(tracker, igdb, follow, clock, sender):
    add(tracker, igdb, name="Очень длинное название игры для кнопки в сводке")
    run(tracker.poll_due())
    follow.answers["1"] = series(follow_up("2", "Очень-очень длинное название следующей игры серии"))
    clock.advance(days=7)
    run(tracker.poll_due())
    clock.advance(hours=3)

    run(tracker.deliver_pending())

    [(_, buttons)] = sender.sent
    assert buttons[0].label == "👀 Следить: Очень-очень длинное название следующей игры серии"
    assert buttons[1].label == "📄 Карточка: Очень длинное название игры для кнопки"[:30 + len("📄 Карточка: ") - 1] + "…"


def test_outside_a_summary_each_announcement_is_a_message_of_its_own_with_plain_buttons(
    tracker, igdb, follow, clock, sender
):
    title_id = announce(tracker, igdb, follow, clock, hours=4)  # 16:00: after the summary

    run(tracker.deliver_pending())

    assert len(sender.sent) == 2
    by_text = {message.splitlines()[0]: buttons for message, buttons in sender.sent}
    assert by_text["🎮 Анонсировано дополнение: Elden Ring: Shadow of the Erdtree"] == [
        Action("👀 Следить", FOLLOW, "game:3"), Action("📄 Карточка", CARD, title_id),
    ]
    assert by_text["🎮 Анонсирована новая игра серии: Elden Ring Nightreign"] == [
        Action("👀 Следить", FOLLOW, "game:2"), Action("📄 Карточка", CARD, title_id),
    ]


# --- «Недавно» (7.6) --------------------------------------------------------------------------------------------------


def test_the_feed_offers_follow_under_a_game_announcement_and_in_the_list_after_it(tracker, igdb, follow, clock):
    announce(tracker, igdb, follow, clock)

    rows = {row.headline: row for day in run(tracker.feed()).recent for row in day.rows}

    expansion = rows["🎮 Анонсировано дополнение: Elden Ring: Shadow of the Erdtree"]
    assert expansion.follow == FollowOffer(Followable(TitleKind.GAME, "3"), None)
    assert expansion.details == ("Дополнение к игре «Elden Ring»", "Выход: дата не объявлена")

    igdb.put("3", game(), "Elden Ring: Shadow of the Erdtree")
    followed = run(tracker.follow("game", "3")).title_id
    rows = {row.headline: row for day in run(tracker.feed()).recent for row in day.rows}

    assert rows["🎮 Анонсировано дополнение: Elden Ring: Shadow of the Erdtree"].follow == FollowOffer(
        Followable(TitleKind.GAME, "3"), followed
    )
    assert rows["🎮 Анонсирована новая игра серии: Elden Ring Nightreign"].follow.title_id is None


def test_an_announcement_of_the_old_format_has_no_button(tracker, igdb, follow, clock):
    title_id = add(tracker, igdb, name="Elden Ring")
    run(tracker.record_event(follow_ups.SEQUEL_ANNOUNCED, {"text": "🎮 Анонс без данных"}, "old", title_id=title_id))

    rows = [row for day in run(tracker.feed()).recent for row in day.rows]

    assert [row.follow for row in rows] == [None]


# --- an announcement while the owner follows its game (section 8) -------------------------------------------------------


def test_the_message_still_comes_when_the_owner_followed_the_game_meanwhile(tracker, igdb, follow, clock, sender):
    announce(tracker, igdb, follow, clock)
    igdb.put("2", game(), "Elden Ring Nightreign")
    followed = run(tracker.follow("game", "2"))  # from the card, before the summary

    clock.advance(hours=3)
    run(tracker.deliver_pending())

    [(message, buttons)] = sender.sent
    assert "Анонсирована новая игра серии: Elden Ring Nightreign" in message
    assert "game:2" in {a.arg for a in buttons}
    again = run(tracker.follow("game", "2"))  # the press on the button of the message
    assert again.created is False and again.title_id == followed.title_id


# --- «Тестовое событие» (6.6) -------------------------------------------------------------------------------------------


def test_the_two_new_samples_are_in_the_menu_after_the_game_ones(tracker):
    ids = [sample.id for sample in tracker.test_samples()]

    assert ids.index("game-expansion") == ids.index("game-sequel") - 1
    assert ids.index("game-expansion") > ids.index("game-released")
    labels = {s.id: s.label for s in tracker.test_samples()}
    assert labels["game-expansion"] == "Игра: анонсировано дополнение" and labels["game-sequel"] == "Игра: новая игра серии"


@pytest.mark.parametrize(
    "sample_id, text",
    [
        (
            "game-expansion",
            "🎮 Анонсировано дополнение: Ведьмак 3: Дикая Охота — Баллады прошлого\n"
            "Дополнение к игре «Ведьмак 3: Дикая охота»\nВыход: 2027",
        ),
        (
            "game-sequel",
            "🎮 Анонсирована новая игра серии: The Witcher IV\nПродолжение игры «Ведьмак 3: Дикая охота»\nВыход: 2028",
        ),
    ],
)
def test_a_new_sample_comes_with_its_text_and_no_buttons(tracker, sender, sample_id, text):
    result = run(tracker.send_test_event(sample_id))

    assert result.delivered is True
    [(message, buttons)] = sender.sent
    assert message.endswith(text) and message.startswith("🧪 Тестовое событие")
    assert buttons == []


def test_the_sample_ids_do_not_clash_with_each_other(tracker):
    sample_ids = [sample.id for sample in tracker.test_samples()]

    assert len(sample_ids) == len(set(sample_ids))
