"""Bot side of the tracker core: the menu, `/start`, «Сводка сейчас», the buttons under messages and cards, and the Telegram sender.

Two modes by the app address (`APP_URL`, `AppLinks`). Chat mode (no address): the menu is «Мои тайтлы», «Сводка сейчас»,
«Тестовое событие», and «Карточка» sends the card to the chat. Link mode: «Карточка» is a link button to the app, a card in
the chat has the one button «Открыть в приложении», the menu is «Сводка сейчас» alone, and the old texts of the menu are
answered with a link. The list and the test event live in `list_handlers` and `test_event_handlers`. The buttons under
messages and cards are «Посмотрел», «Следить», «Карточка», «Удалить» and the link «🛒 Открыть в Steam» (a button with an
address opens the page itself, the bot never hears of it).

Handlers talk to the core only through the `Tracker` facade. They live on one router with the owner filter on it;
a handler never checks the owner itself. A title is added by sending the bot a post or a name: every message no
handler here takes goes to «Входящие» (`inbox_handlers`, registered last). «➕ Добавить» is gone; its text from an old
keyboard on the phone gets a sentence about that and the new keyboard, its old buttons are dead.
"""

import html
import logging
from collections.abc import Sequence

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LinkPreviewOptions,
    Message,
    ReplyKeyboardMarkup,
)

from app.bot.app_links import AppLinks
from app.bot.card_message import send_card_message
from app.bot.inbox_handlers import TitleCards, register_inbox_handlers
from app.bot.list_handlers import (
    CARD_PREFIX,
    MY_TITLES_BUTTON,
    confirm_markup,
    delete_question,
    register_list_handlers,
)
from app.bot.test_event_handlers import (
    RULES_CHECK_BUTTON,
    RULES_CHECK_CALLBACK,
    TEST_EVENT_BUTTON,
    register_test_event_handlers,
)
from app.tracker.actions import CARD, DELETE, FOLLOW, SEASONS, WATCHED, Action, card_actions
from app.tracker.cards import TitleCard, format_card
from app.tracker.core import (
    CARD_SIZE,
    TitleNotFound,
    Tracker,
    UnknownEvent,
    UnknownKind,
    UnknownSeason,
    UnknownTitle,
    WatchableSeason,
    poster_url,
)
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind

__all__ = [
    "ADD_BUTTON", "BOT_COMMANDS", "MALFORMED_TOKEN", "MY_TITLES_BUTTON", "RULES_CHECK_BUTTON", "RULES_CHECK_CALLBACK",
    "SUMMARY_BUTTON", "TEST_EVENT_BUTTON", "TelegramSender", "actions_markup", "main_keyboard",
    "register_tracker_handlers", "seasons_markup",
]  # the buttons that live in `list_handlers` and `test_event_handlers` are told here too: callers know one module

ADD_BUTTON = "➕ Добавить"  # gone from the keyboard; the old keyboard on the phone still sends it
SUMMARY_BUTTON = "📋 Сводка сейчас"
OPEN_IN_APP_BUTTON = "📄 Открыть в приложении"  # the one button of a card in the chat in link mode
_OLD_ADD_PREFIXES = ("tadd:", "tpick:")  # the kind menu and the suggestions of «Добавить»: dead buttons now
_ACTION_PREFIX = "tact:"  # tact:<action name>:<number>, see app.tracker.actions
_SEASON_PREFIX = "tsid:"  # tsid:<title id>:<season record id> flips a mark, tsid:<title id>:done closes the choice
# the buttons sent before the seasons were known by their records: tsea:<title id>:<season number> (or :done). The number
# of an anime season may have changed since, so such a button only says it is out of date
_OLD_SEASON_PREFIX = "tsea:"
_STALE_SEASON_BUTTON = "Эта кнопка устарела — откройте карточку заново"
_DONE = "done"
_DELETE_PREFIX = "tdel:"  # tdel:y:<title id> deletes after the question, tdel:n:<title id> drops it
_YES, _NO = "y", "n"

SUMMARY_COMMAND = "summary"
BOT_COMMANDS = [BotCommand(command=SUMMARY_COMMAND, description="Сводка сейчас")]  # shown in Telegram's «/» menu
# aiogram refuses to make a bot of such a token; the process starts without one (`app.main`), and the start script
# looks for these words in the log
MALFORMED_TOKEN = "токен бота неверного вида — проверьте TELEGRAM_BOT_TOKEN в .env"
START_TEXT = (
    "👋 Бот работает. Чтобы добавить фильм, сериал, аниме или игру, перешлите мне пост о нём или напишите название: "
    "я найду и предложу добавить, а что не найду — сохраню во «Входящие» веб-приложения.\n\n"
    "Кнопки меню внизу: «Мои тайтлы» — ваш список, «Сводка сейчас» присылает накопленные события, «Тестовое событие» "
    "показывает, как выглядят сообщения, и проверяет правила доставки."
)
START_TEXT_LINK = (  # link mode: the text link «🌐 Открыть приложение» follows it
    "👋 Бот работает. Чтобы добавить фильм, сериал, аниме или игру, перешлите мне пост о нём или напишите название: "
    "я найду и предложу добавить, а что не найду — сохраню во «Входящие» приложения.\n\n"
    "Кнопка «Сводка сейчас» присылает накопленные события. Список, карточки, тестовое событие и настройки — "
    "в приложении: "
)
OPEN_APP_LINK = "🌐 Открыть приложение"
LIST_MOVED_TEXT, OPEN_LIST_LINK = "Список теперь в приложении: ", "📚 Открыть список"
TEST_EVENT_MOVED_TEXT = "Тестовое событие и проверка правил доставки теперь в Настройках приложения: "
OPEN_SETTINGS_LINK = "⚙️ Открыть Настройки"
NO_ADD_BUTTON = "Кнопки «Добавить» больше нет: просто перешлите мне пост или напишите название."
_NOT_IN_LIST = "Этого тайтла больше нет в списке."
_DEAD_BUTTON = "Эта кнопка больше не работает."
_ADDING = "Добавляю…"
_ASK_SEASONS = (
    "Какие сезоны вы уже посмотрели? Нажмите на сезон, чтобы отметить его; "
    "повторное нажатие снимает отметку. Когда закончите, нажмите «Готово»."
)


def _action_button(action: Action, links: AppLinks | None = None) -> InlineKeyboardButton:
    """A button with an address opens it (the game in Steam); in link mode «Карточка» opens the card in the app; the
    others call the bot."""
    if action.url is not None:
        return InlineKeyboardButton(text=action.label, url=action.url)
    if links is not None and action.name == CARD and isinstance(action.arg, int):
        return InlineKeyboardButton(text=action.label, url=links.card(action.arg))
    return InlineKeyboardButton(text=action.label, callback_data=f"{_ACTION_PREFIX}{action.name}:{action.arg}")


def actions_markup(actions: Sequence[Action], links: AppLinks | None = None) -> InlineKeyboardMarkup | None:
    """One button per row under a message; None when there is nothing to press."""
    if not actions:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[_action_button(a, links)] for a in actions])


class TelegramSender:
    """Delivers tracker messages to the owner's chat. Without a bot (a malformed token) every send fails, and the
    queue keeps the event, as with no network. With `links` (link mode) the «Карточка» buttons open the app."""

    def __init__(self, bot: Bot | None, chat_id: int, links: AppLinks | None = None) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._links = links

    async def send(self, message: str, actions: Sequence[Action] = ()) -> None:
        if self._bot is None:
            raise RuntimeError(MALFORMED_TOKEN)
        await self._bot.send_message(
            chat_id=self._chat_id, text=message, reply_markup=actions_markup(actions, self._links)
        )


def main_keyboard(links: AppLinks | None = None) -> ReplyKeyboardMarkup:
    """The menu at the bottom of the chat: one button in link mode, three in chat mode."""
    rows = [[KeyboardButton(text=SUMMARY_BUTTON)]]
    if links is None:
        rows = [[KeyboardButton(text=MY_TITLES_BUTTON)], *rows, [KeyboardButton(text=TEST_EVENT_BUTTON)]]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def _with_link(text: str, label: str, url: str) -> str:
    """HTML of a message that ends with a text link (a message with the menu cannot carry a button under it)."""
    return f"{html.escape(text, quote=False)}<a href=\"{html.escape(url)}\">{html.escape(label, quote=False)}</a>"


def seasons_markup(title_id: int, seasons: Sequence[WatchableSeason]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅ ' if s.watched else ''}Сезон {s.number}",
                callback_data=f"{_SEASON_PREFIX}{title_id}:{s.id}",
            )
        ]
        for s in seasons
    ]
    rows.append([InlineKeyboardButton(text="Готово", callback_data=f"{_SEASON_PREFIX}{title_id}:{_DONE}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kind_of(raw: str) -> TitleKind | None:
    """The kind a button names; None for text that is no kind (a button of an older version of the bot)."""
    try:
        return TitleKind(raw)
    except ValueError:
        return None


def register_tracker_handlers(
    dp: Dispatcher, tracker: Tracker, allowed_user_ids: list[int], links: AppLinks | None = None
) -> Router:
    """Put every tracker handler on one router behind the owner filter and include it in `dp`.

    The filter is the second line of defence behind `AccessMiddleware`: an update from anyone else, or from nobody
    (no sender), matches no handler. A new handler goes on this router and never checks the owner itself. `links`
    set is link mode, `None` is chat mode (module description).
    """
    router = Router(name="tracker")
    owner = F.from_user.id.in_(frozenset(allowed_user_ids))
    router.message.filter(owner)
    router.callback_query.filter(owner)

    async def answer_with_link(message: Message, text: str, label: str, url: str) -> None:
        """The new menu comes with the answer (it replaces the old one on the phone), so the link is in the text."""
        await message.answer(
            _with_link(text, label, url), parse_mode="HTML", reply_markup=main_keyboard(links),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    async def start(message: Message) -> None:
        if links is None:
            await message.answer(START_TEXT, reply_markup=main_keyboard())
        else:
            await answer_with_link(message, START_TEXT_LINK, OPEN_APP_LINK, links.home())

    async def list_moved(message: Message) -> None:
        await answer_with_link(message, LIST_MOVED_TEXT, OPEN_LIST_LINK, links.list())

    async def test_event_moved(message: Message) -> None:
        await answer_with_link(message, TEST_EVENT_MOVED_TEXT, OPEN_SETTINGS_LINK, links.settings())

    # --- «Сводка сейчас» ------------------------------------------------------------------------

    async def send_summary_now(message: Message) -> None:
        try:
            result = await tracker.summary_now()
        except Exception as exc:  # the queue is read from the database: tell the owner, keep the bot alive
            logging.warning("summary now failed: %s", repr(exc))
            await message.answer("Не удалось собрать сводку. Попробуйте ещё раз.")
            return
        if result.events == 0:
            await message.answer("Накопленных событий нет — присылать нечего.")
        elif not result.delivered:
            await message.answer("Не удалось отправить сводку. События остались в очереди и придут позже.")

    # --- «Добавить» is gone ----------------------------------------------------------------------

    async def no_add_button(message: Message) -> None:
        await message.answer(NO_ADD_BUTTON, reply_markup=main_keyboard(links))

    async def refuse_old_add_button(callback: CallbackQuery) -> None:
        await callback.answer(_DEAD_BUTTON)

    async def tell_failure(callback: CallbackQuery, text: str) -> None:
        """After the early answer the press has no popup left: a failure goes to the chat as a message."""
        if callback.message is None:
            logging.warning("no message to tell the owner: %s", text)
            return
        await callback.message.answer(text)

    async def ask_seasons_in(message: Message, title_id: int) -> bool:
        """Offer the seasons with released episodes for marking. False: a movie or nothing is out yet."""
        seasons = await tracker.watchable_seasons(title_id)
        if not seasons:
            return False
        await message.answer(_ASK_SEASONS, reply_markup=seasons_markup(title_id, seasons))
        return True

    async def ask_watched_seasons(callback: CallbackQuery, title_id: int) -> bool:
        return callback.message is not None and await ask_seasons_in(callback.message, title_id)

    def card_markup(card: TitleCard) -> InlineKeyboardMarkup | None:
        """Under a card in the chat: its buttons, or in link mode the one that opens the card in the app (what the
        other buttons do is done in the app)."""
        if links is None:
            return actions_markup(card_actions(card))
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=OPEN_IN_APP_BUTTON, url=links.card(card.id))]]
        )

    async def send_card_in(message: Message, card: TitleCard, heading: str | None = None) -> None:
        text = format_card(card) if heading is None else f"{heading}\n\n{format_card(card)}"
        await send_card_message(message, text, poster_url(card.poster_path, CARD_SIZE), card_markup(card))

    async def send_card(callback: CallbackQuery, card: TitleCard | None, heading: str | None = None) -> None:
        if card is None or callback.message is None:
            return
        await send_card_in(callback.message, card, heading)

    async def show_title(message: Message, title_id: int, heading: str) -> None:
        """The card of a title of the list after a heading; a title deleted on the web meanwhile shows nothing."""
        card = await tracker.title_card(title_id)
        if card is not None:
            await send_card_in(message, card, heading)

    async def show_card_of(callback: CallbackQuery, title_id: int) -> None:
        card = await tracker.title_card(title_id)
        if card is None:
            await callback.answer(_NOT_IN_LIST)
            return
        await callback.answer()
        await send_card(callback, card)

    async def show_card(callback: CallbackQuery) -> None:
        try:
            title_id = int(callback.data.removeprefix(CARD_PREFIX))
        except ValueError:
            title_id = -1
        await show_card_of(callback, title_id)

    # --- buttons under messages and cards -------------------------------------------------------

    async def drop_buttons(callback: CallbackQuery) -> None:
        """A pressed button is spent: take the keyboard off its message."""
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as exc:  # an old or missing message: the answer to the press matters more
            logging.debug("could not remove buttons: %s", repr(exc))

    async def drop_pressed_button(callback: CallbackQuery) -> None:
        """Only the pressed button is spent: the others under the message (a summary's other titles) stay."""
        markup = getattr(callback.message, "reply_markup", None)  # an old message comes without its keyboard
        if markup is None:
            return
        rows = [[b for b in row if b.callback_data != callback.data] for row in markup.inline_keyboard]
        rows = [row for row in rows if row]
        try:
            await callback.message.edit_reply_markup(
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
            )
        except Exception as exc:  # an old or missing message: the answer to the press matters more
            logging.debug("could not remove the pressed button: %s", repr(exc))

    async def mark_watched(callback: CallbackQuery, title_id: int) -> None:
        try:
            result = await tracker.mark_watched(title_id)
        except UnknownTitle:
            await callback.answer(_NOT_IN_LIST)
            return
        except Exception as exc:
            logging.warning("marking a title watched failed: %s", repr(exc))
            await callback.answer("Не удалось сохранить. Попробуйте ещё раз.")
            return
        await drop_pressed_button(callback)
        if not result.changed:
            await callback.answer("Уже отмечено как просмотренное.")
            return
        await callback.answer("Отмечено как просмотренное")
        card = await tracker.title_card(title_id)
        if callback.message is not None and card is not None:
            await callback.message.answer(
                f"✅ Просмотрено: {card.name}\nФильм в архиве. Раз в неделю я проверю, не анонсировано ли продолжение."
            )

    async def follow_title(callback: CallbackQuery, raw: str) -> None:
        """`raw` is "<kind>:<id>" on a button of the current kind (a film's sequel, an expansion or a game of the series),
        or the number of the announcement on an old one, which is a film's."""
        kind, _, external_id = raw.partition(":")
        old_event = raw.isascii() and raw.isdigit()
        if not old_event and not (_kind_of(kind) and external_id):
            await callback.answer(_DEAD_BUTTON)
            return
        source = KINDS[_kind_of(kind) or TitleKind.MOVIE].source_name  # an old button has no kind: its sequel is a film's
        await callback.answer(_ADDING)  # the source may take longer than Telegram waits for the answer
        try:
            if old_event:
                result = await tracker.follow_sequel(int(raw))
            else:
                result = await tracker.follow(kind, external_id)
        except UnknownEvent:
            await tell_failure(callback, "Это объявление больше недоступно.")
            return
        except UnknownKind:
            await tell_failure(callback, _DEAD_BUTTON)
            return
        except TitleNotFound:
            await tell_failure(callback, f"Не нашёл это в {source}. Попробуйте чуть позже.")
            return
        except Exception as exc:
            logging.warning("following a title failed: %r, cause: %r", exc, exc.__cause__)
            await tell_failure(callback, f"Не удалось получить данные из {source}. Попробуйте чуть позже.")
            return
        await drop_pressed_button(callback)
        heading = "✅ Добавлено в список" if result.created else "Уже в списке"
        await send_card(callback, await tracker.title_card(result.title_id), heading)

    async def open_seasons_choice(callback: CallbackQuery, title_id: int) -> None:
        if await tracker.title_card(title_id) is None:
            await callback.answer(_NOT_IN_LIST)
            return
        if not await ask_watched_seasons(callback, title_id):
            await callback.answer("Пока нет вышедших сезонов, отмечать нечего.")
            return
        await callback.answer()

    async def refuse_old_season_button(callback: CallbackQuery) -> None:
        await callback.answer(_STALE_SEASON_BUTTON)

    async def flip_season(callback: CallbackQuery) -> None:
        raw_id, _, raw_season = callback.data.removeprefix(_SEASON_PREFIX).partition(":")
        if not (raw_id.isascii() and raw_id.isdigit()):
            await callback.answer("Эта кнопка больше не работает.")
            return
        title_id = int(raw_id)
        if raw_season == _DONE:
            card = await tracker.title_card(title_id)
            if card is None:
                await callback.answer(_NOT_IN_LIST)
                return
            await drop_buttons(callback)
            await callback.answer("Готово")
            await send_card(callback, card)
            return
        if not (raw_season.isascii() and raw_season.isdigit()):
            await callback.answer("Эта кнопка больше не работает.")
            return
        try:
            seasons = await tracker.toggle_season(title_id, int(raw_season))
        except UnknownTitle:
            await callback.answer(_NOT_IN_LIST)
            return
        except UnknownSeason:
            await callback.answer("Такого сезона нет или он ещё не вышел.")
            return
        except Exception as exc:
            logging.warning("marking a season failed: %s", repr(exc))
            await callback.answer("Не удалось сохранить. Попробуйте ещё раз.")
            return
        await callback.answer()
        try:
            await callback.message.edit_reply_markup(reply_markup=seasons_markup(title_id, seasons))
        except Exception as exc:  # the marks are saved; a stale message only keeps its old look
            logging.debug("could not refresh the season buttons: %s", repr(exc))

    # --- «Удалить» ------------------------------------------------------------------------------

    async def ask_delete(callback: CallbackQuery, title_id: int) -> None:
        card = await tracker.title_card(title_id)
        if card is None:
            await callback.answer(_NOT_IN_LIST)
            return
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(
                delete_question([card.name]),
                reply_markup=confirm_markup(f"{_DELETE_PREFIX}{_YES}:{title_id}", f"{_DELETE_PREFIX}{_NO}:{title_id}"),
            )

    async def answer_delete(callback: CallbackQuery) -> None:
        answer, _, raw_id = callback.data.removeprefix(_DELETE_PREFIX).partition(":")
        if answer not in (_YES, _NO) or not (raw_id.isascii() and raw_id.isdigit()):
            await callback.answer("Эта кнопка больше не работает.")
            return
        if answer == _NO:
            await drop_buttons(callback)
            await callback.answer("Отменено, тайтл остался в списке.")
            return
        try:
            result = await tracker.delete_title(int(raw_id))
        except UnknownTitle:
            await drop_buttons(callback)
            await callback.answer(_NOT_IN_LIST)
            return
        except Exception as exc:  # the question stays, so the press can be repeated
            logging.warning("deleting a title failed: %s", repr(exc))
            await callback.answer("Не удалось удалить. Попробуйте ещё раз.")
            return
        await drop_buttons(callback)
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(f"🗑 Удалено: {result.name}")

    async def press_action(callback: CallbackQuery) -> None:
        name, _, raw = callback.data.removeprefix(_ACTION_PREFIX).partition(":")
        number = int(raw) if raw.isascii() and raw.isdigit() else None
        if name == FOLLOW:
            await follow_title(callback, raw)
        elif number is not None and name == WATCHED:
            await mark_watched(callback, number)
        elif number is not None and name == SEASONS:
            await open_seasons_choice(callback, number)
        elif number is not None and name == CARD:
            await show_card_of(callback, number)
        elif number is not None and name == DELETE:
            await ask_delete(callback, number)
        else:
            await callback.answer(_DEAD_BUTTON)

    router.message.register(start, CommandStart())
    router.message.register(send_summary_now, Command(SUMMARY_COMMAND))
    router.message.register(send_summary_now, F.text == SUMMARY_BUTTON)
    router.message.register(no_add_button, F.text == ADD_BUTTON)
    if links is not None:  # the old texts of the menu: an old keyboard on the phone still sends them
        router.message.register(list_moved, F.text == MY_TITLES_BUTTON)
        router.message.register(test_event_moved, F.text == TEST_EVENT_BUTTON)
    register_list_handlers(router, tracker, chat_mode=links is None)
    register_test_event_handlers(router, tracker, chat_mode=links is None)

    router.callback_query.register(refuse_old_add_button, F.data.startswith(_OLD_ADD_PREFIXES))
    router.callback_query.register(show_card, F.data.startswith(CARD_PREFIX))
    router.callback_query.register(press_action, F.data.startswith(_ACTION_PREFIX))
    router.callback_query.register(answer_delete, F.data.startswith(_DELETE_PREFIX))
    router.callback_query.register(flip_season, F.data.startswith(_SEASON_PREFIX))
    router.callback_query.register(refuse_old_season_button, F.data.startswith(_OLD_SEASON_PREFIX))

    # last: every message the handlers above did not take is an inbox item
    menu = {TEST_EVENT_BUTTON, MY_TITLES_BUTTON, SUMMARY_BUTTON, ADD_BUTTON}
    register_inbox_handlers(router, tracker, menu, TitleCards(show_title, ask_seasons_in))
    dp.include_router(router)
    return router
