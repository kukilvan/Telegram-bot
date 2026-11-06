"""Reading a Telegram message into an inbox item (spec 1.1 of stage 6.4), without a bot: the text, the bold limits,
`url` and `text_link`, the media words, the rules of the post link."""

from datetime import datetime, timezone

import pytest
from aiogram.types import (
    Animation,
    Chat,
    Document,
    Message,
    MessageEntity,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
    PhotoSize,
    Sticker,
    User,
    Video,
    VideoNote,
    Voice,
)

from app.bot.inbox_message import incoming
from app.tracker.core import MEDIA_WORDS

WHEN = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
OWNER = User(id=42, is_bot=False, first_name="x")


def utf16(text):
    return len(text.encode("utf-16-le")) // 2


def entity(kind, text, piece, **extra):
    """The entity of `piece` inside `text`, with offsets in UTF-16 as Telegram counts them."""
    start = text.index(piece)
    return MessageEntity(type=kind, offset=utf16(text[:start]), length=utf16(piece), **extra)


def message(**fields):
    return Message(message_id=1, date=WHEN, chat=Chat(id=42, type="private"), from_user=OWNER, **fields)


def channel(username, number=12):
    return MessageOriginChannel(
        type="channel", date=WHEN, chat=Chat(id=-100123, type="channel", username=username), message_id=number
    )


# --- text and bold ------------------------------------------------------------------------------------


def test_a_plain_text_is_the_text():
    item = incoming(message(text="Дюна"))

    assert (item.text, item.bold, item.links, item.media, item.post_url, item.forwarded) == ("Дюна", (), (), None, None, False)


def test_a_caption_is_the_text_of_a_picture():
    text = "Новый трейлер Hades II"
    item = incoming(message(
        photo=[PhotoSize(file_id="p", file_unique_id="p", width=1, height=1)], caption=text,
        caption_entities=[entity("bold", text, "Hades II")],
    ))

    assert (item.text, item.bold, item.media) == (text, ("Hades II",), None)


def test_bold_is_cut_by_utf16_offsets_after_an_emoji():
    text = "🎮🔥 Вышла игра Clair Obscur: Expedition 33 — смотрите"
    item = incoming(message(text=text, entities=[entity("bold", text, "Clair Obscur: Expedition 33")]))

    assert item.bold == ("Clair Obscur: Expedition 33",)


@pytest.mark.parametrize(
    "piece, kept",
    [
        ("Один", True),
        ("раз два три четыре пять шесть семь восемь", True),
        ("раз два три четыре пять шесть семь восемь девять", False),
        ("   ", False),
    ],
)
def test_bold_keeps_one_to_eight_words(piece, kept):
    text = f"Начало {piece} конец"
    item = incoming(message(text=text, entities=[entity("bold", text, piece)]))

    assert item.bold == ((piece,) if kept else ())


def test_other_entities_are_not_bold():
    text = "Курсив и код"
    item = incoming(message(text=text, entities=[entity("italic", text, "Курсив"), entity("code", text, "код")]))

    assert item.bold == ()


# --- links -------------------------------------------------------------------------------------------


def test_url_and_text_link_are_links_in_order_and_a_hidden_link_is_never_a_name():
    text = "Страница https://store.steampowered.com/app/1145350/ и Підписатись"
    item = incoming(message(text=text, entities=[
        entity("url", text, "https://store.steampowered.com/app/1145350/"),
        entity("text_link", text, "Підписатись", url="https://t.me/somechannel"),
    ]))

    assert item.links == ("https://store.steampowered.com/app/1145350/", "https://t.me/somechannel")
    assert item.bold == ()


def test_a_link_without_an_entity_stays_only_in_the_text():
    item = incoming(message(text="store.steampowered.com/app/1"))

    assert item.links == () and item.text == "store.steampowered.com/app/1"


# --- media -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fields, media",
    [
        ({"photo": [PhotoSize(file_id="p", file_unique_id="p", width=1, height=1)]}, "photo"),
        ({"video": Video(file_id="v", file_unique_id="v", width=1, height=1, duration=1)}, "video"),
        (
            {
                "animation": Animation(file_id="a", file_unique_id="a", width=1, height=1, duration=1),
                "document": Document(file_id="a", file_unique_id="a"),
            },
            "animation",
        ),
        ({"document": Document(file_id="d", file_unique_id="d")}, "document"),
        (
            {"sticker": Sticker(
                file_id="s", file_unique_id="s", type="regular", width=1, height=1, is_animated=False, is_video=False
            )},
            "sticker",
        ),
        ({"voice": Voice(file_id="o", file_unique_id="o", duration=1)}, "voice"),
        ({"video_note": VideoNote(file_id="n", file_unique_id="n", length=1, duration=1)}, "voice"),
        ({}, "message"),
    ],
)
def test_a_message_without_text_has_its_media_word(fields, media):
    item = incoming(message(**fields))

    assert (item.text, item.media) == ("", media)
    assert item.media in MEDIA_WORDS


def test_the_media_words_read_as_the_spec_says():
    assert MEDIA_WORDS == {
        "photo": "картинка", "video": "видео", "animation": "гифка", "document": "файл", "sticker": "стикер",
        "voice": "голосовое", "message": "сообщение",
    }


def test_an_album_keeps_its_group():
    item = incoming(message(photo=[PhotoSize(file_id="p", file_unique_id="p", width=1, height=1)], media_group_id="13"))

    assert item.media_group_id == "13"


# --- the post link -----------------------------------------------------------------------------------


def test_a_forward_from_a_public_channel_keeps_the_post_link():
    item = incoming(message(text="Пост", forward_origin=channel("gamechannel", 345)))

    assert (item.post_url, item.forwarded) == ("https://t.me/gamechannel/345", True)


@pytest.mark.parametrize(
    "origin",
    [
        channel(None),  # a private channel
        MessageOriginUser(type="user", date=WHEN, sender_user=User(id=5, is_bot=False, first_name="Друг")),
        MessageOriginHiddenUser(type="hidden_user", date=WHEN, sender_user_name="Аноним"),
        MessageOriginChat(type="chat", date=WHEN, sender_chat=Chat(id=-5, type="supergroup", username="group")),
    ],
    ids=["private channel", "user", "hidden user", "group"],
)
def test_other_forwards_have_no_post_link(origin):
    item = incoming(message(text="Пост", forward_origin=origin))

    assert (item.post_url, item.forwarded) == (None, True)
