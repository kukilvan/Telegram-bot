"""Inline answers: Telegram rejects >50 results (regression: 'too many inline query results specified')."""

from aiogram.types import InlineQueryResultArticle, InputTextMessageContent

from app.bot.main import INLINE_MAX_RESULTS, _balance_inline

SOURCES = ["TMDb Movie", "TMDb TV Series", "AniList Anime", "IGDB Game", "Steam Game", "PSN Game"]


def _article(rid, source):
    return InlineQueryResultArticle(
        id=str(rid),
        title=f"{source} {rid}",
        input_message_content=InputTextMessageContent(message_text=f"/add {rid}"),
        description=source,
    )


def _full_answer():
    """10 results from each of 6 sources = 60, exactly the shape that broke the bot."""
    return [_article(i, s) for s in SOURCES for i in range(100, 110)]


def test_never_more_than_telegram_limit():
    assert len(_full_answer()) == 60
    assert len(_balance_inline(_full_answer())) == INLINE_MAX_RESULTS == 50


def test_every_source_stays_represented():
    out = _balance_inline(_full_answer())
    assert {a.description for a in out} == set(SOURCES)


def test_small_answers_are_untouched_and_keep_source_order():
    articles = [_article(1, "TMDb Movie"), _article(2, "TMDb Movie"), _article(3, "IGDB Game")]
    out = _balance_inline(articles)
    assert len(out) == 3
    assert sorted(a.title for a in out) == sorted(a.title for a in articles)


def test_ids_are_unique_even_when_movie_and_series_share_one():
    # TMDb uses one numeric id space for movies and series
    out = _balance_inline([_article(1396, "TMDb Movie"), _article(1396, "TMDb TV Series")])
    assert len({a.id for a in out}) == 2
    assert len(out) == 2


def test_empty():
    assert _balance_inline([]) == []
