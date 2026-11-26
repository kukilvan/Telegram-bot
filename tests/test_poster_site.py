"""Posters of Shikimori on the current address (spec 3.3 of stage 9.1a, KI-21): a stored address of `shikimori.<zone>` or
of its subdomain is shown on the site of SHIKIMORI_BASE_URL, whatever it was stored under; TMDb and IGDB addresses and
anything else never change. The three places that show a poster — the web, the card of the bot, the offer card of
«Входящие» — each get the site from the settings."""

import asyncio

import pytest
from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.bot import inbox_handlers
from app.bot.main import build_dispatcher
from app.tracker.core import (
    CARD_SIZE, LIST_SIZE, InboxOutcome, InboxReply, OfferCard, Tracker, poster_url, shikimori_site,
)
from app.tracker import posters
from inbox_fakes import Clients, tracker_on
import test_tracker_titles_bot as titles_bot
from test_tracker_titles_bot import DUNE_2, OWNER, run
from test_web_layout import ROW, make_app, render

movies, tracker = titles_bot.movies, titles_bot.tracker  # the fixtures, by their names

SITE = "https://shikimori.io"
OLD = "https://shikimori.one/uploads/poster/animes/1/a.jpg"
NEW = "https://shikimori.io/uploads/poster/animes/1/a.jpg"
IGDB = "https://images.igdb.com/igdb/image/upload"


@pytest.mark.parametrize("stored, site, expected", [
    (OLD, SITE, NEW),  # the example of the spec
    ("https://desu.shikimori.one/system/x.jpg", SITE, "https://desu.shikimori.io/system/x.jpg"),  # a subdomain
    ("https://shikimori.io/uploads/x.jpg", SITE, "https://shikimori.io/uploads/x.jpg"),  # already there
    ("https://a.b.shikimori.one/x.jpg?size=2#top", SITE, "https://a.b.shikimori.io/x.jpg?size=2#top"),  # query kept
    (OLD, "https://shikimori.example:8443", "https://shikimori.example:8443/uploads/poster/animes/1/a.jpg"),  # its port
    ("https://shikimori.one:444/x.jpg", SITE, "https://shikimori.io/x.jpg"),  # the stored port is dropped
    (OLD, "https://127.0.0.1:9000", "https://127.0.0.1:9000/uploads/poster/animes/1/a.jpg"),
    ("https://desu.shikimori.one/x.jpg", "https://127.0.0.1:9000", "https://desu.shikimori.one/x.jpg"),  # no subdomain of numbers
    (OLD, None, OLD),  # no valid site: as stored
    (OLD, "", OLD),
    ("https://notshikimori.one/x.jpg", SITE, "https://notshikimori.one/x.jpg"),  # not the label `shikimori`
    ("https://shikimori.example.com/x.jpg", SITE, "https://shikimori.example.com/x.jpg"),  # `shikimori` is not the second label
    ("https://example.com/shikimori.one/x.jpg", SITE, "https://example.com/shikimori.one/x.jpg"),  # the host decides
    ("https://localhost/x.jpg", SITE, "https://localhost/x.jpg"),
    ("https://[::1/x.jpg", SITE, "https://[::1/x.jpg"),  # spoiled: left alone
])
def test_a_shikimori_address_moves_to_the_site_of_the_setting(stored, site, expected):
    assert poster_url(stored, CARD_SIZE, site) == expected


@pytest.mark.parametrize("site", [SITE, None, ""])
def test_tmdb_and_igdb_addresses_never_change(site):
    assert poster_url("/abc.jpg", LIST_SIZE, site) == "https://image.tmdb.org/t/p/w92/abc.jpg"
    assert poster_url(f"{IGDB}/t_thumb/co1.jpg", CARD_SIZE, site) == f"{IGDB}/t_cover_big_2x/co1.jpg"
    assert poster_url("https://image.tmdb.org/x.jpg", CARD_SIZE, site) == "https://image.tmdb.org/x.jpg"


@pytest.mark.parametrize("stored", [None, "", "abc.jpg", "http://shikimori.one/x.jpg"])
def test_what_is_no_poster_stays_no_poster_with_a_site(stored):
    assert poster_url(stored, CARD_SIZE, SITE) is None


@pytest.mark.parametrize("address, expected", [
    ("https://shikimori.io", "https://shikimori.io"),
    (" https://Shikimori.IO/path ", "https://shikimori.io"),
    ("https://shikimori.example:8443/x", "https://shikimori.example:8443"),
    ("http://shikimori.io", None),  # not https
    ("shikimori.io", None),
    ("", None),
    ("https://", None),
    ("https://bad host/", None),
    ("https://shikimori.io:notaport", None),
])
def test_the_site_is_an_https_host_or_none(address, expected):
    assert shikimori_site(address) == expected


def test_the_core_gives_the_site_of_the_pure_module():
    assert shikimori_site is posters.shikimori_site


# --- the three places -------------------------------------------------------------------------------


def test_the_web_shows_the_fixed_address(tmp_path):
    app = make_app(tmp_path, shikimori_base_url=SITE)
    html = app.state.web.templates.env.from_string(ROW).render(
        poster=OLD, size=LIST_SIZE, icon="🎌", name="Атака", original="", year=2013
    )

    assert f'src="{NEW}"' in html and "shikimori.one" not in html


def test_the_web_without_a_valid_site_shows_the_address_as_stored(tmp_path):
    html = render(tmp_path, ROW, poster=OLD, size=LIST_SIZE, icon="🎌", name="Атака", original="", year=2013)

    assert f'src="{OLD}"' in html


def feed(dp, **update):
    asyncio.run(dp.feed_update(Bot(token="123456:TEST"), Update(update_id=1, **update)))


@pytest.fixture
def said(monkeypatch):
    """The `link_preview_options` of every message the bot sent."""
    previews = []

    async def message_answer(self, text=None, **kwargs):
        previews.append(kwargs.get("link_preview_options"))

    async def callback_answer(self, text=None, **kwargs):
        pass

    monkeypatch.setattr(Message, "answer", message_answer)
    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    return previews


@pytest.mark.parametrize("base_url, expected", [(SITE, NEW), ("", OLD), ("http://shikimori.io", OLD)])
def test_the_card_of_the_bot_shows_the_fixed_address(tracker, movies, said, base_url, expected):
    import dataclasses

    movies.by_id[DUNE_2.external_id] = dataclasses.replace(DUNE_2, poster_path=OLD)
    title_id = run(tracker.add_title("movie", DUNE_2.external_id)).title_id
    dp = build_dispatcher(tracker, [OWNER], None, base_url)
    user = User(id=OWNER, is_bot=False, first_name="x")
    message = Message(message_id=1, date=1, chat=Chat(id=OWNER, type="private"), from_user=user, text="menu")

    feed(dp, callback_query=CallbackQuery(
        id="1", from_user=user, chat_instance="c", data=f"tcard:{title_id}", message=message
    ))

    assert said[-1].url == expected


@pytest.mark.parametrize("base_url, expected", [(SITE, NEW), ("", OLD)])
def test_the_offer_card_of_the_inbox_shows_the_fixed_address(monkeypatch, said, base_url, expected):
    monkeypatch.setattr(inbox_handlers, "PAUSE_SECONDS", 0.05)
    offer = InboxReply(InboxOutcome.OFFER, None, OfferCard(1, 0, "Это оно?", OLD))

    async def pause_over(self, item_id):
        return offer

    monkeypatch.setattr(Tracker, "inbox_pause_over", pause_over)
    tracker = tracker_on(Clients())
    dp = build_dispatcher(tracker, [OWNER], None, base_url)
    user = User(id=OWNER, is_bot=False, first_name="x")

    async def go():
        bot = Bot(token="123456:TEST")
        message = Message(message_id=1, date=1, chat=Chat(id=OWNER, type="private"), from_user=user, text="Атака титанов")
        await dp.feed_update(bot, Update(update_id=1, message=message))
        await asyncio.sleep(0.3)

    asyncio.run(go())

    assert said[-1].url == expected
