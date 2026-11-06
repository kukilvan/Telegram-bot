"""Reading a Telegram message of the owner into an `IncomingMessage` (spec 1.1 of stage 6.4), pure: no bot, no database.

The text is `text` or `caption`; bold pieces of 1–8 words; the addresses of the entities `url` and `text_link` (a
hidden link such as «Підписатись» is a link, never a name); the media of a message without text; the post link of a
forward from a public channel only. The offsets of the entities count in UTF-16, so the pieces are cut by aiogram
(`MessageEntity.extract_from`), not by hand.
"""

from aiogram.types import Message, MessageEntity

from app.tracker.core import IncomingMessage

MAX_BOLD_WORDS = 8  # a longer bold piece is a sentence, not a name
_CHANNEL = "channel"  # the type of `forward_origin` of a forward from a channel
# what a message without text is, in the order of the check: an animation comes with its document too
_MEDIA = (
    ("photo", "photo"),
    ("video", "video"),
    ("animation", "animation"),
    ("document", "document"),
    ("sticker", "sticker"),
    ("voice", "voice"),
    ("video_note", "voice"),
)
_OTHER_MEDIA = "message"


def _bold(text: str, entities: list[MessageEntity]) -> tuple[str, ...]:
    pieces = []
    for entity in entities:
        if entity.type != "bold":
            continue
        piece = " ".join(entity.extract_from(text).split())
        if piece and len(piece.split()) <= MAX_BOLD_WORDS:
            pieces.append(piece)
    return tuple(pieces)


def _links(text: str, entities: list[MessageEntity]) -> tuple[str, ...]:
    addresses = []
    for entity in entities:
        if entity.type == "url":
            addresses.append(entity.extract_from(text).strip())
        elif entity.type == "text_link" and entity.url:
            addresses.append(entity.url)
    return tuple(address for address in addresses if address)


def _media(message: Message) -> str:
    for field, media in _MEDIA:
        if getattr(message, field, None):
            return media
    return _OTHER_MEDIA


def _post_url(message: Message) -> str | None:
    origin = message.forward_origin
    if origin is None or origin.type != _CHANNEL:
        return None
    username = getattr(origin.chat, "username", None)
    return f"https://t.me/{username}/{origin.message_id}" if username else None


def incoming(message: Message) -> IncomingMessage:
    """What an inbox item keeps of this message."""
    text = message.text if message.text is not None else (message.caption or "")
    entities = list((message.entities if message.text is not None else message.caption_entities) or [])
    return IncomingMessage(
        text=text,
        bold=_bold(text, entities),
        links=_links(text, entities),
        media=None if text.strip() else _media(message),
        post_url=_post_url(message),
        forwarded=message.forward_origin is not None,
        media_group_id=message.media_group_id,
    )
