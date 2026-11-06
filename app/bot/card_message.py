"""The one function that sends a card to the chat: the text and the buttons with the poster above the text.

The poster is the link preview of its address (`show_above_text`, large), so the card stays a text message and Telegram
fetches the picture itself; when it cannot, the message comes without a preview and the send does not fail. A card with
no poster address carries a disabled preview, the plain text card.
"""

from aiogram.types import InlineKeyboardMarkup, LinkPreviewOptions, Message


def poster_preview(address: str | None) -> LinkPreviewOptions:
    """The preview options of a card: the poster above the text, or no preview at all without an address."""
    if not address:
        return LinkPreviewOptions(is_disabled=True)
    return LinkPreviewOptions(url=address, show_above_text=True, prefer_large_media=True)


async def send_card_message(
    message: Message, text: str, poster: str | None, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    """Send `text` with `reply_markup` and the poster at address `poster` (None: no picture). Any card goes through
    here: a title card, and a card that is not one (an offer of the inbox) gives its own address, text and keyboard."""
    await message.answer(text, reply_markup=reply_markup, link_preview_options=poster_preview(poster))
