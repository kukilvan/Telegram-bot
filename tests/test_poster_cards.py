"""Posters in bot cards (spec 8 of stage 6.4): the address per source and size, and the preview every card of the bot
carries: the poster above the text, or a disabled preview without a poster; other messages carry none."""

import dataclasses

import pytest
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from app.bot.tracker_handlers import MY_TITLES_BUTTON, TEST_EVENT_BUTTON
from app.bot.card_message import poster_preview, send_card_message
from app.tracker.core import CARD_SIZE, LIST_SIZE, poster_url
from app.tracker import posters
import test_tracker_titles_bot as titles_bot
from test_tracker_titles_bot import DUNE_2, DUNE_3, Chat_, run

movies, tracker = titles_bot.movies, titles_bot.tracker  # the fixtures, by their names

IGDB = "https://images.igdb.com/igdb/image/upload"
SHIKI = "https://shikimori.io/uploads/poster/animes/1/x.jpeg"


@pytest.mark.parametrize("stored, size, expected", [
    ("/abc.jpg", CARD_SIZE, "https://image.tmdb.org/t/p/w342/abc.jpg"),
    ("/abc.jpg", LIST_SIZE, "https://image.tmdb.org/t/p/w92/abc.jpg"),
    (f"{IGDB}/t_thumb/co1.jpg", CARD_SIZE, f"{IGDB}/t_cover_big_2x/co1.jpg"),
    (SHIKI, CARD_SIZE, SHIKI),
    (None, CARD_SIZE, None),
    ("", CARD_SIZE, None),
    ("http://insecure.example/x.jpg", CARD_SIZE, None),
])
def test_the_address_of_a_poster_per_source_and_size(stored, size, expected):
    assert poster_url(stored, size) == expected


def test_the_core_gives_the_same_function_as_the_pure_module():
    assert poster_url is posters.poster_url and CARD_SIZE is posters.CARD_SIZE


def test_the_preview_is_the_poster_above_the_text_or_disabled():
    assert poster_preview("https://x/y.jpg") == LinkPreviewOptions(
        url="https://x/y.jpg", show_above_text=True, prefer_large_media=True
    )
    assert poster_preview(None) == LinkPreviewOptions(is_disabled=True)
    assert poster_preview("") == LinkPreviewOptions(is_disabled=True)


@pytest.fixture
def sent(monkeypatch):
    """Every `Message.answer` of the bot with its keyword arguments."""
    said = []

    async def message_answer(self, text=None, **kwargs):
        said.append((text, kwargs))

    async def callback_answer(self, text=None, **kwargs):
        pass

    monkeypatch.setattr(Message, "answer", message_answer)
    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    return said


def test_a_card_that_is_not_a_title_card_goes_through_the_same_function(sent):
    class Stub:
        async def answer(self, text, **kwargs):
            sent.append((text, kwargs))

    run(send_card_message(Stub(), "offer", "https://x/y.jpg", None))
    assert sent[0][1]["link_preview_options"].url == "https://x/y.jpg"


def test_a_title_card_with_a_poster_shows_it_above_the_text(tracker, movies, sent):
    movies.by_id[DUNE_2.external_id] = dataclasses.replace(DUNE_2, poster_path="/dune2.jpg")
    chat = Chat_(tracker)
    title_id = run(tracker.add_title("movie", DUNE_2.external_id)).title_id

    chat.press(f"tcard:{title_id}")

    text, kwargs = sent[-1]
    assert "Дюна: Часть вторая" in text and kwargs["reply_markup"].inline_keyboard
    assert kwargs["link_preview_options"] == LinkPreviewOptions(
        url="https://image.tmdb.org/t/p/w342/dune2.jpg", show_above_text=True, prefer_large_media=True
    )


def test_a_title_card_without_a_poster_has_the_preview_disabled(tracker, sent):
    chat = Chat_(tracker)
    title_id = run(tracker.add_title("movie", DUNE_3.external_id)).title_id

    chat.press(f"tcard:{title_id}")

    assert sent[-1][1]["link_preview_options"] == LinkPreviewOptions(is_disabled=True)


def test_the_list_of_titles_and_the_rules_check_carry_no_preview_options(tracker, sent):
    chat = Chat_(tracker)
    run(tracker.add_title("movie", DUNE_3.external_id))

    chat.say(MY_TITLES_BUTTON)
    chat.say(TEST_EVENT_BUTTON)

    assert len(sent) == 2 and all("link_preview_options" not in kwargs for _, kwargs in sent)
