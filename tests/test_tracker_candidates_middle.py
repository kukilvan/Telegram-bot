"""The candidate rules of stage 9.1d (spec 7.1 and 7.2): a Russian name in the middle of a sentence (KI-58), «from» and a
number after a colon in a Latin run (KI-60), the grown stop list and the common words.

A line of at most 8 words typed by the owner is a name message (4.2 of 6.4), so the texts here are forwarded posts."""

import pytest

from app.tracker.candidate_words import COMMON_WORDS, STOP_NAMES
from app.tracker.candidates import candidates

FILLER = "Эта строка нужна только чтобы текст был длинным и не был названием"
ANCHOR = "Игра Fishy Island вот"  # a name that stays whatever the tested line drops


def pairs(text: str, **kwargs) -> list[tuple[str, float]]:
    return [(c.name, c.weight) for c in candidates(text, forwarded=True, **kwargs)]


def later(line: str, **kwargs) -> list[tuple[str, float]]:
    """What `line` gives on a line that is not the first, besides the anchor (so the fallback of the first line, which
    takes a text with no name, stays out of it, and the line has no bonus of a first line)."""
    found = pairs(f"{FILLER}\n{ANCHOR}\n{line}", **kwargs)
    return [(name, weight) for name, weight in found if name != "Fishy Island"]


# --- KI-58: the middle name (7.1) ---------------------------------------------------------------------------------


def test_the_three_examples_of_the_spec_give_exactly_the_stated_names():
    assert pairs("Вчера вышла новая Дюна, и все рады") == [("Дюна", 2)]
    assert pairs("Смотрю Мастер и Маргарита вечером") == [("Мастер", 2), ("Маргарита", 2)]
    assert pairs("Новый трейлер Дюны") == [("Дюны", 2)]


def test_the_same_examples_typed_as_one_short_line_are_a_name_message():
    assert [(c.name, c.weight) for c in candidates("Новый трейлер Дюны")] == [("Новый трейлер Дюны", 100)]  # «Дюны» merges


def test_a_word_all_in_capitals_is_no_name():
    assert later("Сегодня АНОНС новой игры вышел тут") == []
    assert later("Сегодня вышел АНОНС тут и ещё") == []
    assert later("Сегодня вышел анонс ДЮНА тут") == []
    assert later("Сегодня вышел ПрИвет тут") == []


@pytest.mark.parametrize("text", [
    "Он ушёл. Потом вернулся и всё",  # the first word of the sentences
    "Он ушёл! Потом вернулся? Тогда Дальше тут",
    "Он ушёл… Потом вернулся и всё",
    "🎬 Дюна вышла вчера и все рады",  # after an emoji at the start of a line
    "— Дюна вышла вчера и все рады",
    "«Дюна вышла вчера и все рады",
])
def test_the_first_word_of_a_sentence_is_no_name(text):
    found = later(text)

    assert [name for name, _ in found] == ([] if "Тогда" not in text else ["Дальше"])


def test_the_run_of_a_sentence_start_goes_on_at_its_second_word():
    assert later("Смотрю Мастер вечером и ещё слова") == [("Мастер", 2)]
    assert later("Мы ушли. Дальше Мастер Маргарита тут") == [("Мастер Маргарита", 2)]


def test_a_run_has_at_most_four_words():
    assert later("Купил Один Два Три Четыре Пять вот") == [("Один Два Три Четыре", 2)]
    assert later("Купил Один Два Три Четыре вот") == [("Один Два Три Четыре", 2)]


def test_a_name_with_an_apostrophe_and_with_yo_is_one_word():
    assert later("Вышла новая Зв'язок и ещё слова") == [("Зв'язок", 2)]
    assert later("Вышла новая Нёва и ещё слова") == [("Нёва", 2)]
    assert later("Вышла новая Їжак и ещё слова") == [("Їжак", 2)]


def test_a_run_inside_a_quote_a_bold_piece_or_after_a_kind_word_has_the_weight_of_that_rule():
    assert later("Вышла «Новая Дюна» вчера и все рады") == [("Новая Дюна", 3)]
    assert later("Вышла новая Дюна вчера и все рады", bold=("Дюна",)) == [("Дюна", 8)]
    assert later("Вышла новая Дюна вчера и все рады", bold=("новая Дюна",)) == [("новая Дюна", 8)]
    assert later("Вышел фильм Новая Дюна вчера и все рады") == [("Новая Дюна вчера и все рады", 5)]


def test_a_run_right_after_a_marker_is_no_name():
    assert later("Это сделали студия Бунги вчера и все рады") == []
    assert later("Игру сделал разработчик Кристоф Баррас вчера") == []
    assert later("Вышла игра от Бунги вчера и все рады") == []


def test_a_common_word_ends_a_run_and_alone_is_nothing():
    assert later("Мы знаем Вы Дюна Январь Мастер тут и всё") == [("Дюна", 2), ("Мастер", 2)]
    assert later("Спасибо Вам и Вашей Богу Господи Боже слова") == []
    assert later("Это будет Сентября Пятницы Воскресенья слова") == []
    assert later("Это будет Дюна Рождество и Пасха слова") == [("Дюна", 2)]


@pytest.mark.parametrize("word", COMMON_WORDS)
def test_every_common_word_alone_is_nothing(word):
    assert later(f"Это вот {word} там слова слова") == []


def test_a_repeat_adds_the_bonus_of_any_name():
    assert later("Вышла Дюна вчера, а Дюна завтра тоже") == [("Дюна", 2 + 2 + 2)]  # each time 2, the repeat 2 more


def test_names_of_places_and_people_come_up_too_with_the_low_weight():
    assert later("Вчера в Москве показали Илон Маск и слова") == [("Москве", 2), ("Илон Маск", 2)]


def test_a_latin_title_stays_ahead_of_a_middle_name():
    assert pairs("Вышла новая Дюна и Dune вчера и все рады") == [("Dune", 10), ("Дюна", 2)]


# --- KI-60: «from» and the number after a colon (7.2) -----------------------------------------------------------------


def test_a_leading_from_is_dropped_and_the_rest_weighs_as_after_a_marker():
    assert pairs("Игра from Software вышла вчера и все очень этому рады сегодня") == [("Software", 5)]
    assert later("Игра from Software вышла вчера и все очень этому рады") == [("Software", 0)]
    assert later("Игра From Software вышла вчера и все очень этому рады") == [("Software", 0)]
    assert later("Игра FROM Software Inc вышла вчера и все очень этому рады") == [("Software Inc", 1)]


def test_a_kind_word_before_from_no_longer_counts():
    assert later("Игра Software вышла вчера и все очень этому рады") == [("Software", 9)]
    assert later("Игра from Software вышла вчера и все очень этому рады") == [("Software", 0)]


def test_from_alone_is_nothing_and_in_the_middle_of_a_run_it_stays():
    assert later("Вот from и ещё слова слова слова слова") == []
    assert later("Вот Games from Software и ещё слова слова") == [("Games from Software", 6)]


def test_a_number_after_a_colon_joins_the_name():
    assert pairs("Вышел Fallout: 76 вчера и все очень этому рады сегодня вечером") == [("Fallout: 76", 10)]
    assert later("Вышел Fallout: 76 вчера и все рады") == [("Fallout: 76", 6)]
    assert later("Вышел Resident Evil: 4 вчера и все рады") == [("Resident Evil: 4", 6)]


@pytest.mark.parametrize("episode", [
    "серия", "серии", "серию", "Серия", "серія", "епізод", "эпизод", "Эпизод", "episode", "Episode",
    "episodes", "ep", "Ep.", "EP",
])
def test_a_number_before_an_episode_word_stays_the_episode_line(episode):
    found = dict(later(f"Bleach: 3 {episode} вышла вчера"))

    assert "Bleach: 3" not in found and "Bleach" in found


def test_the_episode_line_of_the_spec_keeps_its_head():
    assert [name for name, _ in pairs("Bleach: 3 серия")] == ["Bleach"]
    assert later("Bleach: 3 серия") == [("Bleach", 55)]  # the head of an episode line 50 and the lone Latin word 6 - 1


def test_a_word_that_only_starts_like_ep_is_no_episode_word():
    assert later("Вышел Fallout: 76 epic вчера и все рады")[0][0] == "Fallout: 76 epic"


# --- the stop list (7.3) ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "Crunchyroll", "Kinopoisk", "Кинопоиск", "Okko", "Иви", "Wink", "Amediateka", "Prime Video", "Apple TV", "Hulu",
    "Paramount+", "Game Pass", "PS Plus", "Gamescom", "The Game Awards", "Summer Game Fest", "State of Play",
    "Nintendo Direct", "Reddit", "VK", "Kotaku", "Polygon", "Eurogamer", "GameSpot", "StopGame", "Игромания", "DTF",
])
def test_the_services_igdb_does_not_know_are_on_the_stop_list(name):
    assert name in STOP_NAMES
    assert later(f"Вчера в «{name}» вышел материал и все рады") == []
    assert later(f"Вчера {name.upper()} показал игру и все рады") == []
