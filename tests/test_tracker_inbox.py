"""«Входящие» in the core (spec 1, 7, 10 of stage 6.4): taking in and joining, the states and the moves of an item,
the 12 hours, deleting, numbers never reused, the query, an item across a restart."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.tracker.core import IncomingMessage, InboxReason, InboxState, PauseOutcome, Tracker, UnknownInboxItem
from app.tracker.db import create_session_factory
from app.tracker.candidates import text_query as query_of
from app.tracker.inbox import MAX_TEXT
from app.tracker.models import InboxRecord, TitleKind

T0 = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def after(self, **delta):
        self.now += timedelta(**delta)


class FakeSender:
    async def send(self, message, actions=()):
        pass


@pytest.fixture
def clock():
    return Clock()


def make_tracker(clock, url="sqlite://"):
    return Tracker(create_session_factory(url), clock=clock, sender=FakeSender())


@pytest.fixture
def tracker(clock):
    return make_tracker(clock)


def take(tracker, text="", **fields):
    return run(tracker.take_in(IncomingMessage(text=text, **fields)))


def item(tracker, item_id):
    return run(tracker.inbox_item(item_id))


def states(tracker):
    return [(i.id, i.state, i.reason) for i in (item(tracker, n) for n in range(1, 10)) if i is not None]


# --- taking in ----------------------------------------------------------------------------------------


def test_a_text_is_one_waiting_item_with_everything_kept(tracker):
    result = take(
        tracker, "Отличный пост про **Hades II**", bold=("Hades II",), links=("https://example.com",),
        post_url="https://t.me/gamechannel/12", forwarded=True,
    )

    assert (result.item_id, result.joined, result.moved) == (1, False, 0)
    entry = item(tracker, 1)
    assert (entry.state, entry.reason, entry.kind) == (InboxState.WAITING, None, None)
    assert entry.text == "Отличный пост про **Hades II**"
    assert entry.bold == ("Hades II",) and entry.links == ("https://example.com",)
    assert entry.post_url == "https://t.me/gamechannel/12" and entry.forwarded is True
    assert entry.received_at == datetime(2026, 11, 6, 12, 0) and entry.moved_at is None


def test_a_message_without_text_keeps_its_media(tracker):
    take(tracker, media="sticker")

    entry = item(tracker, 1)
    assert (entry.text, entry.media) == ("", "sticker")


def test_the_text_is_cut_to_ten_thousand_characters(tracker):
    take(tracker, "я" * (MAX_TEXT + 500))

    assert len(item(tracker, 1).text) == MAX_TEXT


def test_an_album_is_one_item_with_its_caption(tracker, clock):
    take(tracker, "Подпись альбома", media_group_id="album")
    for _ in range(4):
        clock.after(seconds=0.3)
        assert take(tracker, media="photo", media_group_id="album").joined

    entry = item(tracker, 1)
    assert entry.text == "Подпись альбома"
    assert item(tracker, 2) is None


def test_a_forward_after_its_comment_is_one_item_the_comment_first(tracker, clock):
    take(tracker, "Посмотри это", bold=("это",))
    clock.after(seconds=1)
    result = take(tracker, "Пост канала", bold=("Пост",), post_url="https://t.me/ch/5", forwarded=True)

    assert result.joined and result.item_id == 1
    entry = item(tracker, 1)
    assert entry.text == "Посмотри это\n\nПост канала"
    assert entry.bold == ("это", "Пост") and entry.post_url == "https://t.me/ch/5" and entry.forwarded


def test_a_forwarded_album_after_its_comment_is_one_item(tracker, clock):
    take(tracker, "Комментарий")
    clock.after(seconds=0.5)
    take(tracker, "Пост", forwarded=True, media_group_id="a")
    clock.after(seconds=0.5)
    take(tracker, media="photo", forwarded=True, media_group_id="a")

    assert item(tracker, 1).text == "Комментарий\n\nПост" and item(tracker, 2) is None


def test_exactly_two_seconds_still_joins(tracker, clock):
    take(tracker, "Комментарий")
    clock.after(seconds=2)

    assert take(tracker, "Пост", forwarded=True).joined


def test_after_two_seconds_a_forward_is_an_item_of_its_own(tracker, clock):
    take(tracker, "Комментарий")
    clock.after(seconds=2, milliseconds=1)

    result = take(tracker, "Пост", forwarded=True)

    assert not result.joined and result.item_id == 2


def test_two_names_one_second_apart_are_two_items(tracker, clock):
    take(tracker, "Дюна")
    clock.after(seconds=1)

    assert take(tracker, "Hades").item_id == 2


def test_two_forwards_in_one_go_are_two_items(tracker, clock):
    take(tracker, "Пост один", forwarded=True)
    clock.after(seconds=0.1)

    result = take(tracker, "Пост два", forwarded=True)

    assert (result.item_id, result.joined, result.moved) == (2, False, 1)
    assert item(tracker, 1).reason == InboxReason.NO_ANSWER


def test_another_album_is_another_item(tracker, clock):
    take(tracker, "Один", media_group_id="a")
    clock.after(seconds=0.1)

    assert take(tracker, "Два", media_group_id="b").item_id == 2


# --- the moves ---------------------------------------------------------------------------------------


def test_five_posts_in_a_row_leave_four_in_the_inbox_and_the_last_waiting(tracker, clock):
    moved = []
    for n in range(5):
        moved.append(take(tracker, f"Пост {n}").moved)
        clock.after(seconds=10)

    assert moved == [0, 1, 1, 1, 1]
    assert states(tracker) == [
        *[(n, InboxState.INBOX, InboxReason.NO_ANSWER) for n in range(1, 5)], (5, InboxState.WAITING, None),
    ]
    assert run(tracker.inbox_count()) == 4
    assert [i.id for i in run(tracker.inbox_items())] == [4, 3, 2, 1]


def test_two_waiting_items_left_from_before_are_both_moved_by_the_next_new_one(tracker, clock):
    """An older version or a crash can leave two items waiting; the next new item moves both."""
    with tracker.session_factory() as session:
        for text in ("Старый один", "Старый два"):
            session.add(InboxRecord(
                state=InboxState.WAITING, text=text, forwarded=False, received_at=datetime(2026, 11, 6, 11, 0),
                last_message_at=datetime(2026, 11, 6, 11, 0),
            ))
        session.commit()

    result = take(tracker, "Новый")

    assert result.moved == 2
    assert [(i.id, i.reason) for i in run(tracker.inbox_items())] == [
        (2, InboxReason.NO_ANSWER), (1, InboxReason.NO_ANSWER),
    ]
    assert item(tracker, 3).state == InboxState.WAITING


def test_the_end_of_the_pause_asks_about_an_item_with_text(tracker):
    take(tracker, "Дюна")

    assert run(tracker.inbox_pause_over(1)) == PauseOutcome.ASK
    assert item(tracker, 1).state == InboxState.WAITING


def test_the_end_of_the_pause_moves_an_item_without_text(tracker):
    take(tracker, media="voice")

    assert run(tracker.inbox_pause_over(1)) == PauseOutcome.NO_TEXT
    entry = item(tracker, 1)
    assert (entry.state, entry.reason, entry.moved_at) == (InboxState.INBOX, InboxReason.NO_TEXT, datetime(2026, 11, 6, 12, 0))


@pytest.mark.parametrize("setup", ["moved", "gone"])
def test_the_end_of_the_pause_says_nothing_of_an_item_that_no_longer_waits(tracker, clock, setup):
    take(tracker, "Дюна")
    if setup == "moved":
        clock.after(seconds=10)
        take(tracker, "Другое")
    else:
        run(tracker.forget_inbox_item(1))

    assert run(tracker.inbox_pause_over(1)) == PauseOutcome.NOTHING


def test_a_kind_is_stored_and_the_item_goes_to_the_inbox_not_found(tracker, clock):
    take(tracker, "Тест один")
    clock.after(minutes=1)

    run(tracker.answer_kind(1, TitleKind.GAME))

    entry = item(tracker, 1)
    assert (entry.state, entry.reason, entry.kind) == (InboxState.INBOX, InboxReason.NOT_FOUND, TitleKind.GAME)
    assert entry.moved_at == datetime(2026, 11, 6, 12, 1)


def test_a_kind_of_an_item_in_the_inbox_updates_its_kind_and_reason_and_moves_nothing(tracker, clock):
    take(tracker, "Первый")
    clock.after(seconds=10)
    take(tracker, "Второй")

    run(tracker.answer_kind(1, TitleKind.MOVIE))

    first, second = item(tracker, 1), item(tracker, 2)
    assert (first.state, first.reason, first.kind) == (InboxState.INBOX, InboxReason.NOT_FOUND, TitleKind.MOVIE)
    assert first.moved_at == datetime(2026, 11, 6, 12, 0, 10)  # when it went there first
    assert second.state == InboxState.WAITING


def test_a_kind_of_a_gone_item_is_refused(tracker):
    with pytest.raises(UnknownInboxItem):
        run(tracker.answer_kind(9, TitleKind.MOVIE))


# --- the 12 hours ------------------------------------------------------------------------------------


def test_eleven_hours_fifty_nine_stay_and_twelve_hours_move(tracker, clock):
    take(tracker, "Дюна")
    clock.after(hours=11, minutes=59)
    assert run(tracker.expire_inbox()) == 0
    assert item(tracker, 1).state == InboxState.WAITING

    clock.after(minutes=1)
    assert run(tracker.expire_inbox()) == 1

    entry = item(tracker, 1)
    assert (entry.state, entry.reason) == (InboxState.INBOX, InboxReason.NO_ANSWER)
    assert run(tracker.expire_inbox()) == 0


def test_the_twelve_hours_count_from_the_arrival_not_from_a_joined_message(tracker, clock):
    take(tracker, "Комментарий")
    clock.after(seconds=2)
    take(tracker, "Пост", forwarded=True)
    clock.after(hours=12, seconds=-2)

    assert run(tracker.expire_inbox()) == 1


# --- deleting ----------------------------------------------------------------------------------------


def test_not_saving_deletes_and_a_second_time_finds_nothing(tracker):
    take(tracker, "Дюна")

    assert run(tracker.forget_inbox_item(1)) is True
    assert item(tracker, 1) is None
    assert run(tracker.forget_inbox_item(1)) is False


def test_resolving_deletes_and_a_gone_item_is_no_error(tracker):
    take(tracker, "Дюна")

    run(tracker.resolve_inbox(1))
    run(tracker.resolve_inbox(1))

    assert item(tracker, 1) is None


def test_the_number_of_a_deleted_last_item_is_never_reused(tracker, clock):
    take(tracker, "Дюна")
    run(tracker.forget_inbox_item(1))
    clock.after(seconds=10)

    assert take(tracker, "Hades").item_id == 2


# --- the query and a restart -------------------------------------------------------------------------


def test_the_query_is_the_text_cut_at_a_word():
    assert query_of("Дюна") == "Дюна"
    assert query_of("  Дюна:\n  Часть  вторая ") == "Дюна: Часть вторая"
    long = "Слово " * 20
    assert query_of(long) == "Слово Слово Слово Слово Слово Слово Слово Слово Слово Слово"
    assert len(query_of("я" * 100)) == 60
    assert query_of("") == ""


def test_the_item_keeps_its_query_and_a_joined_text_renews_it(tracker, clock):
    take(tracker, "Посмотри")
    assert item(tracker, 1).query == "Посмотри"
    take(tracker, "Пост про игру", forwarded=True)

    assert item(tracker, 1).query == "Посмотри Пост про игру"


def test_the_item_survives_a_new_core_on_the_same_file(tmp_path, clock):
    url = f"sqlite:///{tmp_path / 'tracker.db'}"
    take(make_tracker(clock, url), "Дюна")

    again = make_tracker(clock, url)  # a restart: the bot memory is empty, the database is not
    assert item(again, 1).text == "Дюна"
    clock.after(hours=12)
    assert run(again.expire_inbox()) == 1
    assert run(again.inbox_count()) == 1
