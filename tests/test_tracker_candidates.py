"""Name candidates and links of sources (spec 3 and 4 of stage 6.4): the 18 samples of idea 001 against the table of 4.6,
every rule of 4.1–4.5 on a made-up text, the years, the name key, the links of every form, the query of an item."""

import re
from pathlib import Path

import pytest

from app.tracker import candidates as module
from app.tracker.candidates import SourceLink, candidates, name_key, query_of, source_links, text_query, years
from app.tracker.models import TitleKind

SAMPLES_FILE = Path(__file__).parent / "fixtures" / "inbox_samples.md"
# sample -> the first candidate with its weight and the names right after it (4.6). «Meta Horizon» of the table of 4.6 is
# on the stop list of 4.5, so it is not a candidate.
EXPECTED = {
    1: ("Ghost in the SQL Data", 14, []),
    2: ("Dead-End Job", 14, [("Игры в кальмара", 3), ("Разделения", 0.5)]),
    3: ("Petit Planet", 6, [("Animal Crossing от HoYoverse", 4), ("Геншине", 0.5)]),
    4: ("Death Stranding: Isolations", 14, [("E&H production", 1)]),
    5: ("Phantom Blade Zero", 10, [("Black Myth: Wukong", 6), ("Elden Ring", 6)]),
    6: ("Блич", 4, []),
    7: ("EXODUS", 10, [("Mass Effect", 5)]),
    8: ("Silent Hill: Townfall", 10, []),
    9: ("Alien: Isolation 2", 10, []),
    10: ("The Wolf Among Us Remastered", 10, []),
    11: ("Fishy", 24, [("Scary Baboon", 6), ("Enver", 2), ("Animal Company", 1)]),
    12: ("Fabula Rasa", 18, [("Pixel Ripped", 6), ("XR Experience", 6), ("Best of Tech", 6),
                              ("Miami Filmgate Interactive", 6), ("Arvore Immersive", 1), ("SXSW", 1)]),
    13: ("Магия вернувшегося должна быть особенной", 50, [("kikansha no mahou", 50)]),
    14: ("Реинкарнация безработного", 50, [("mushoku tensei", 50)]),
    15: ("Phantom Blade Zero", 10, []),
    16: ("Tomb Raider: Legacy of Atlantis", 18, []),
    17: ("ELDEN RING", 14, []),
    18: ("Control: Resonant", 10, []),
}
# a first line of 12 words that holds no name: with it, the next line is "not the first" and nothing is a name message
FILLER = "Эта строка нужна только чтобы текст был длинным и не был названием"
# the tail that makes a line longer than 8 words
PAD = " вышла вчера и все очень этому рады сегодня вечером"
ANCHOR = "Игра Fishy Island вот"  # a name that stays whatever the tested line drops (weight 10)


def samples() -> dict[int, str]:
    text = SAMPLES_FILE.read_text(encoding="utf-8")
    found = re.finditer(r"^## (\d+)\. .*?\n.*?```text\n(.*?)\n```", text, re.S | re.M)
    return {int(match.group(1)): match.group(2) for match in found}


def pairs(text: str, **kwargs) -> list[tuple[str, float]]:
    return [(c.name, c.weight) for c in candidates(text, **kwargs)]


def names(text: str, **kwargs) -> list[str]:
    return [c.name for c in candidates(text, **kwargs)]


def weight(text: str, name: str, **kwargs) -> float:
    return dict(pairs(text, **kwargs))[name]


def later(line: str) -> str:
    """The text whose second line is `line`."""
    return f"{FILLER}\n{line}"


def rest(line: str) -> list[str]:
    """What `line` gives besides the anchor, on a line that is not the first."""
    return [name for name in names(f"{FILLER}\n{ANCHOR}\n{line}") if name != "Fishy Island"]


def test_the_file_holds_all_18_samples():
    assert sorted(samples()) == list(range(1, 19))


@pytest.mark.parametrize("number", range(1, 19))
def test_each_sample_gives_the_first_name_of_the_table_and_the_next_ones_right_after_it(number):
    first, first_weight, after = EXPECTED[number]
    found = pairs(samples()[number])
    assert found[0] == (first, first_weight)
    assert found[1:1 + len(after)] == after


def test_meta_horizon_of_sample_11_is_on_the_stop_list():
    assert "Meta Horizon" not in names(samples()[11])


# --- 4.1 cleaning ---------------------------------------------------------------------------------------------------


def test_score_lines_and_their_words_are_dropped():
    lines = ("IGN 9/10", "GameSpot 8.5/10", "Famitsu 7,5 / 10", "Metacritic – 85 балів", "Opencritic – 84 points",
             "Famitsu 36 баллов", "Eurogamer 8 бал", "Kotaku 7 бали", "Edge 9 балл")
    for line in lines:
        assert rest(line) == [], line
    assert pairs("Hades 2" + PAD + "\nIGN 9/10\nGameSpot 8.5/10") == [("Hades 2", 10)]


def test_the_signature_of_a_channel_is_dropped():
    for signature in ("Синдром Гравця | Підписатись (http://t.me/x/)", "Gamer News | Subscribe", "SUBSCRIBE to Gamer News",
                      "Подписаться на Gamer Channel", "Подпишись на Gamer Channel"):
        assert rest(signature) == [], signature


def test_invisible_characters_are_removed():
    assert pairs("Hades​ 2­" + PAD + "\nㅤ\nᅟᅠ﻿") == [("Hades 2", 10)]
    assert names("​Ha⁠des" + PAD) == ["Hades"]
    assert pairs("​‌‍‎‏⁠﻿ㅤ") == []


def test_urls_and_handles_are_cut_out_of_a_line():
    text = "Дорама Hades 2" + PAD + "\nhttps://example.com/Secret @gamer t.me/Channel (http://t.me/Other/)"
    assert pairs(text) == [("Hades 2", 6 + 4 + 4)]
    assert rest("t.me/Other https://example.com/Secret (http://t.me/Third/) @zavtracast") == []


def test_a_lone_label_is_dropped_but_a_two_word_line_is_not():
    assert pairs("Main:\nRu:") == []
    assert pairs("Hades 2" + PAD + "\nMain: https://jut.su/xx-yy/s1e1\nRu:") == [("xx yy", 50), ("Hades 2", 10)]
    assert pairs("Главные герои:") == [("Главные герои", 100)]


# --- 4.2 weights ----------------------------------------------------------------------------------------------------


def test_a_name_message_weighs_100():
    assert pairs("Блич") == [("Блич", 100)]
    assert pairs("  Control: Resonant!  ")[0] == ("Control: Resonant", 110)  # plus the Latin run of the same line
    assert pairs("один два три четыре пять шесть семь восемь") == [("один два три четыре пять шесть семь восемь", 100)]


def test_a_forward_a_long_line_and_two_lines_are_no_name_message():
    assert pairs("Блич", forwarded=True) == [("Блич", 1)]
    assert pairs("один два три четыре пять шесть семь восемь девять") == [("один два три четыре пять шесть семь восемь", 1)]
    assert pairs("Один\nДва") == [("Один", 1)]


def test_the_head_of_an_episode_line_weighs_50():
    assert pairs("Реинкарнация безработного: 14 серия (3 сезон)\nMain:") == [("Реинкарнация безработного", 50)]
    assert pairs("Блич: 3 эпизод. Много слов тут в этой строке") == [("Блич", 50)]
    assert pairs("Мультик: 3 серія" + PAD) == [("Мультик", 50)]
    assert pairs("Bleach: 3 серия (2 сезон) вышла вчера и все этому рады") == [("Bleach", 50 + 10)]  # and a Latin run


def test_a_slug_of_jut_su_weighs_50_and_both_sites_make_one_name():
    text = "Серия вышла" + PAD + "\nhttps://jut.su/kikansha-no-mahou/s2e3\nhttps://jutsu.ru/kikansha-no-mahou/s2e3"
    assert pairs(text) == [("kikansha no mahou", 50)] or ("kikansha no mahou", 50) in pairs(text)
    entities = ("https://JUT.SU/Mushoku-Tensei/s3e1", "http://www.jutsu.ru/mushoku-tensei/")
    assert pairs(later("Просто текст про что-то там и всё"), links=entities)[0] == ("Mushoku Tensei", 50)
    no_slug = pairs(later("Просто текст"), links=("https://jut.su/", "https://jut.su/-"))
    assert 50 not in [weight_ for _, weight_ in no_slug]


def test_a_bold_piece_adds_8_to_a_name_found_by_other_rules_and_is_a_name_alone():
    base = "Новая игра Fishy вышла. Рыбалка там, и всё такое"
    assert weight(base, "Fishy") == 14
    assert weight(base, "Fishy", bold=("Fishy",)) == 22  # the same occurrence: no +2 for it
    assert pairs("Дюна\nтекст про фильм вообще", bold=("Дюна",))[0] == ("Дюна", 8)
    assert pairs(later("Текст без названий"), bold=("Игра  года​",)) == [("Игра года", 8)]


def test_a_latin_run_weighs_6_and_the_first_line_adds_4():
    assert weight(later("Вторая строка Hades Two тут"), "Hades Two") == 6
    assert weight("Hades Two" + PAD, "Hades Two") == 10


def test_a_latin_run_after_a_kind_word_adds_4_and_after_a_marker_loses_5():
    assert weight(later("Очень известная игра Hades Two и всё"), "Hades Two") == 10
    assert weight(later("Студия Hades Two вот"), "Hades Two") == 1
    assert weight(later("обычная фраза и Hades Two вот"), "Hades Two") == 6
    assert weight("Игра Hades Two" + PAD, "Hades Two") == 14
    assert weight("От Hades Two" + PAD, "Hades Two") == 5


def test_one_latin_word_off_the_first_line_loses_1_unless_it_is_all_capitals():
    assert weight(later("Фраза про Fishy вот"), "Fishy") == 5
    assert weight(later("Фраза про FISHY вот"), "FISHY") == 6
    assert weight("Fishy" + PAD, "Fishy") == 10


def test_a_run_joins_words_with_a_colon_a_dash_and_inner_hyphens():
    assert "Death Stranding: Isolations" in names("Хочу Death Stranding: Isolations" + PAD)
    assert "Dead-End Job" in names("Хочу Dead-End Job" + PAD)
    assert "Sonic - Mania Plus" in names("Хочу Sonic - Mania Plus" + PAD)
    assert "Tom Clancy's Rainbow Six" in names("Хочу Tom Clancy's Rainbow Six" + PAD)
    assert "Alien: Isolation 2" in names("Хочу Alien: Isolation 2" + PAD)
    assert rest("Вышел Bleach: 3 вот") == ["Bleach"]  # a bare number after a colon is no part of the name


def test_a_quote_weighs_3_plus_1_at_the_start_of_the_first_line_and_half_after_a_marker():
    assert pairs("Текст про «Дюну»" + PAD) == [("Дюну", 3)]
    assert pairs("«Дюна»" + PAD) == [("Дюна", 4)]
    assert pairs("‼\"Дюна\"" + PAD) == [("Дюна", 4)]
    assert pairs("Это смесь «Дюны»" + PAD) == [("Дюны", 0.5)]
    assert pairs("Это как в „Дюне“" + PAD) == [("Дюне", 0.5)]
    assert pairs("Это сериал “Дюна”" + PAD)[0] == ("Дюна", 3)
    assert pairs(later("«Дюна»" + PAD)) == [("Дюна", 3)]  # off the first line: no +1


def test_a_quote_is_1_to_80_characters_and_a_latin_run_inside_it_belongs_to_it():
    assert rest("Вокруг «" + "я" * 81 + "» вот") == []
    assert rest("Вокруг «" + "я" * 80 + "» вот") == ["я" * 80]
    assert pairs(later("Текст про «Hades Two» вот и ещё слова слова")) == [("Hades Two", 3)]


def test_a_cyrillic_name_after_a_kind_word_weighs_5():
    assert pairs(later("Вышел сериал Игра престолов, второй сезон")) == [("Игра престолов", 5)]
    assert pairs(later("Вышла игра Ведьмак Три: Дикая охота")) == [("Ведьмак Три", 5)]
    assert pairs(later("Вышел фильм Дюна часть вторая большая новая")) == [("Дюна часть вторая большая новая", 5)]
    assert pairs(later("Вышел фильм Дюна один два три четыре пять шесть семь")) == [("Дюна один два три четыре пять", 5)]


def test_a_cyrillic_name_needs_a_capital_and_a_kind_word_right_before_it():
    assert rest("Вышла игра очень хорошая и всё тут вообще") == []
    assert rest("Вышел сериал, Дюна по нему и тут слова") == []
    assert rest("Вышла хорошая Дюна и тут слова") == []
    assert weight(later("Вышел сериал Dune тут и ещё слова слова"), "Dune") == 9  # a Latin name is the Latin rule's


def test_with_nothing_found_the_first_line_up_to_a_stop_mark_is_the_candidate():
    assert pairs("Очень длинная фраза про что-то такое. Вторая фраза тут") == [("Очень длинная фраза про что-то такое", 1)]
    assert pairs("Очень длинная фраза — про что-то совсем другое и ещё слова") == [("Очень длинная фраза", 1)]
    assert pairs("Очень длинная фраза – про что-то совсем другое и ещё слова") == [("Очень длинная фраза", 1)]
    assert pairs("Раз два три четыре пять шесть семь восемь девять десять") == [("Раз два три четыре пять шесть семь восемь", 1)]
    assert pairs("Счёт 9/10\nПервая строка текста про что-то и всё, да") == [("Первая строка текста про что-то и всё, да", 1)]
    assert pairs("") == []
    assert pairs("https://t.me/channel/1") == []


def test_a_name_found_again_adds_2_for_each_extra_time():
    assert weight(later("Hades Two тут"), "Hades Two") == 6
    assert weight(later("Hades Two тут\nHades Two там"), "Hades Two") == 6 * 2 + 2
    assert weight(later("Hades Two тут\nHades Two там\nHades Two тоже"), "Hades Two") == 6 * 3 + 2 * 2
    assert weight(later("«Hades Two» там\nИ Hades Two тоже"), "Hades Two") == 3 + 6 + 2  # a quote and a run


def test_ranking_goes_by_weight_then_by_the_first_appearance():
    text = later("Игра Alpha Beta вот\nИгра Gamma Delta вот\nТекст «Омега» тут")
    assert names(text) == ["Alpha Beta", "Gamma Delta", "Омега"]
    found = candidates(text)
    assert found[0].first < found[1].first < found[2].first
    assert names(later("Игра Gamma Delta вот\nИгра Alpha Beta вот")) == ["Gamma Delta", "Alpha Beta"]


# --- 4.3 dropped runs, 4.5 stop list and merging --------------------------------------------------------------------


def test_digits_and_punctuation_only_are_no_run():
    assert rest("Обновление 1.6.0 вышло, цена 2027 и 12:30 - 14:00 тут") == []
    assert rest("Цена 418 и 12.5 - 14.5 тут") == []


def test_a_platform_or_a_store_at_the_start_of_a_run_drops_it():
    for run in ("Xbox Series", "Nintendo Switch 1", "PlayStation Plus", "PS5 Pro", "Switch 2", "Steam Deck", "Quest 3",
                "xbox one", "PS4"):
        assert rest(f"Вышла на {run} вот") == [], run
    assert rest("Вышла на Steam вот и ещё что-то") == []
    assert rest("Вышла на Quest вот и ещё что-то") == []
    assert rest("Вышла Questionable Content тут") == ["Questionable Content"]  # only a whole word is a store


def test_one_short_word_is_dropped_off_the_first_line_only():
    assert rest("У них UG и One вот") == []
    assert rest("У них Hades вот") == ["Hades"]
    assert pairs("UG" + PAD) == [("UG", 10)]


def test_the_stop_list_is_compared_by_the_name_key():
    for name in module.STOP_NAMES:
        assert name_key(name) in module._STOP_KEYS, name
        if name.isascii() and name_key(name) and not name.startswith("Switch"):
            assert rest(f"Тут {name} вот") == [], name
    assert rest("Тут MAPPA и mappa и Epic  Games  Store и Itch.io вот") == []
    assert rest("Тут «Netflix» «стим» «Epic  Games  Store» вот") == ["стим"]


def test_a_name_of_less_than_two_characters_digits_only_or_over_8_words_is_dropped():
    assert rest("Игра «Я» вот и всё тут") == []
    assert rest("Игра «2027» вот и всё тут") == []
    assert rest("Игра «один два три четыре пять шесть семь восемь девять» вот") == []
    assert rest("Игра «один два три четыре пять шесть семь восемь» вот") == ["один два три четыре пять шесть семь восемь"]


def test_a_name_inside_a_longer_one_merges_into_it_and_its_appearances_count():
    assert pairs(later("У меня Fishy Planet и Fishy")) == [("Fishy Planet", 6 + 2)]
    text = "Ghost in the SQL Data и SQL" + PAD
    assert pairs(text) == [("Ghost in the SQL Data", 10 + 2)]
    assert pairs(later("Игра Ghost in the SQL Data тут и Ghost in the SQL")) == [("Ghost in the SQL Data", 10 + 2)]


def test_merging_keeps_the_earliest_position_and_works_in_chains():
    found = candidates(later("У меня Fishy и Fishy Planet вот"))
    assert [c.name for c in found] == ["Fishy Planet"]
    assert found[0].first == len(FILLER) + 1 + len("У меня ")
    assert pairs(later("Тут Fishy и Fishy Planet и Fishy Planet Two")) == [("Fishy Planet Two", 6 + 2 * 2)]


def test_a_name_is_not_merged_when_its_words_are_not_whole_words_of_the_longer_one():
    assert sorted(names(later("Тут Fish и Fishy Planet вот"))) == ["Fish", "Fishy Planet"]


# --- 4.4 kind words and markers ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("word", [
    "игра", "игры", "игру", "игре", "гра", "гри", "гру", "сериал", "сериала", "сериале", "сериалу", "серіал", "серіалу",
    "серіалі", "аниме", "аніме", "фильм", "фильма", "фильме", "фильму", "фільм", "фільму", "фільмі", "мультфильм",
    "мультфильма", "экранизация", "экранизации", "экранизацию", "екранізація", "екранізації", "екранізацію", "ремастер",
    "ремейк", "дорама", "дорамы", "дораму", "экшн", "экшен", "лайфсим", "симулятор", "приключение", "приключения",
    "Игра", "ФИЛЬМ",
])
def test_a_kind_word_adds_4_to_the_run_after_it(word):
    assert weight(later(f"Вот {word} Hades Two тут"), "Hades Two") == 10


@pytest.mark.parametrize("marker", [
    "смесь", "смесью", "как в", "как у", "вроде", "наподобие", "аналог", "аналогом", "в духе", "похож", "похожая",
    "наследник", "наступник", "наступника", "преемник", "известной по", "відомої за", "вытеснив", "помимо", "кроме",
    "после", "на основе", "по мотивам", "от", "від", "студия", "студії", "компания", "компанії", "издатель",
    "видавець", "разработчик", "розробник", "выходцами из", "из", "магазине", "фестивале", "От",
])
def test_a_marker_takes_5_from_the_run_after_it(marker):
    assert weight(later(f"Вот {marker} Hades Two тут"), "Hades Two") == 1


def test_a_marker_must_end_the_text_before_a_name_and_start_a_word():
    assert weight(later("Вот от Hades Two тут"), "Hades Two") == 1
    assert weight(later("Вот отец Hades Two тут"), "Hades Two") == 6
    assert weight(later("Вот похожа на Hades Two тут"), "Hades Two") == 6
    assert weight(later("Вот известной по серии Hades Two тут"), "Hades Two") == 6
    assert weight(later("Вот игра Hades Two тут"), "Hades Two") == 10


# --- years, name key ------------------------------------------------------------------------------------------------


def test_years_of_an_item():
    text = "Премьера в 2027 году, снято в 2019, раньше в 1987 и 1950, но не 1949, 2100, 12027 или 20271"
    assert years(text) == (1950, 1987, 2019, 2027)
    assert years("Реліз 2027р. і 2028-го") == (2027, 2028)
    assert years("") == ()


def test_the_name_key_ignores_case_yo_and_signs():
    assert name_key("Control: Resonant") == name_key("Control Resonant") == "control resonant"
    assert name_key("  Ёлки-палки!  ") == "елки палки"
    assert name_key("Xbox Series X|S") == "xbox series x s"
    assert name_key("???") == ""


def test_two_writings_of_a_name_are_one_candidate():
    assert pairs(later("Игра Control: Resonant тут\nИ Control Resonant там")) == [("Control: Resonant", 10 + 6 + 2)]


def test_names_are_compared_only_through_the_name_key():
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "casefold" not in source and "ё" not in source
    assert source.count("name_key(") >= 4


def test_the_module_is_pure_and_short():
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert sorted(re.findall(r"^(?:from|import) (\S+)", source, re.M)) == [
        "app.tracker.models", "app.tracker.text", "dataclasses", "re", "urllib.parse"]
    assert len(source.splitlines()) <= 400


# --- 3 links of sources -----------------------------------------------------------------------------------------------


def link(address: str):
    found = source_links("", (address,))
    return found[0] if found else None


@pytest.mark.parametrize("address, expected", [
    ("https://store.steampowered.com/app/1245620/ELDEN_RING/", SourceLink("steam", "1245620", TitleKind.GAME)),
    ("http://STORE.steampowered.com/app/4000000", SourceLink("steam", "4000000", TitleKind.GAME)),
    ("store.steampowered.com/app/10", SourceLink("steam", "10", TitleKind.GAME)),
    ("https://www.themoviedb.org/movie/550-fight-club", SourceLink("tmdb_movie", "550", TitleKind.MOVIE)),
    ("https://themoviedb.org/movie/550", SourceLink("tmdb_movie", "550", TitleKind.MOVIE)),
    ("https://www.themoviedb.org/ru/movie/550-fight-club?language=ru", SourceLink("tmdb_movie", "550", TitleKind.MOVIE)),
    ("https://www.themoviedb.org/pt-BR/movie/550/", SourceLink("tmdb_movie", "550", TitleKind.MOVIE)),
    ("https://www.themoviedb.org/tv/1399-game-of-thrones/season/1", SourceLink("tmdb_tv", "1399", TitleKind.SERIES)),
    ("http://themoviedb.org/tv/1399", SourceLink("tmdb_tv", "1399", TitleKind.SERIES)),
    ("https://shikimori.one/animes/20-naruto", SourceLink("shikimori", "20", TitleKind.ANIME)),
    ("https://shikimori.me/animes/z1535-death-note", SourceLink("shikimori", "1535", TitleKind.ANIME, "z")),
    ("https://www.Shikimori.io/animes/y40000", SourceLink("shikimori", "40000", TitleKind.ANIME, "y")),
    ("https://www.imdb.com/title/tt0137523/", SourceLink("imdb", "tt0137523", None)),
    ("imdb.com/title/tt0944947", SourceLink("imdb", "tt0944947", None)),
    ("https://www.imdb.com/en/title/tt0944947/?ref_=x", SourceLink("imdb", "tt0944947", None)),
])
def test_every_form_of_a_link_of_a_source(address, expected):
    assert link(address) == expected


@pytest.mark.parametrize("address", [
    "https://t.me/channel/12", "https://www.youtube.com/watch?v=abc", "https://example.com/app/12",
    "https://store.steampowered.com/bundle/12", "https://store.steampowered.com/app/abc",
    "https://themoviedb.org/person/12", "https://themoviedb.org/movie/", "https://shikimori.one/mangas/12",
    "https://evil-imdb.com/title/tt1", "https://imdb.com.evil.net/title/tt1", "https://notshikimori.one/animes/1",
    "https://jut.su/kikansha-no-mahou/s2e3", "not a link", "http://[::1", "",
])
def test_other_links_are_not_sources(address):
    assert link(address) is None


def test_the_kinds_of_links_are_kinds_of_titles():
    found = source_links("", (
        "https://store.steampowered.com/app/1", "https://themoviedb.org/movie/2", "https://themoviedb.org/tv/3",
        "https://shikimori.one/animes/4"))
    assert [item.kind for item in found] == [TitleKind.GAME, TitleKind.MOVIE, TitleKind.SERIES]  # three at most


def test_links_come_in_order_without_repeats_at_most_three():
    entities = (
        "https://store.steampowered.com/app/1",
        "https://www.themoviedb.org/movie/550-fight-club",
        "https://store.steampowered.com/app/1/Same",  # the same number
        "https://themoviedb.org/ru/movie/550",  # the same movie in another form
        "https://t.me/channel",
        "https://themoviedb.org/tv/3",
        "https://shikimori.one/animes/4",
        "https://www.imdb.com/title/tt1",
    )
    found = source_links("", entities)
    assert [(item.source, item.ref) for item in found] == [("steam", "1"), ("tmdb_movie", "550"), ("tmdb_tv", "3")]


def test_the_links_of_the_text_count_too_and_a_hidden_link_comes_from_the_entities():
    text = "Смотрите: https://shikimori.one/animes/20-naruto, а ещё (https://www.imdb.com/title/tt0137523/)."
    assert [item.source for item in source_links(text)] == ["shikimori", "imdb"]
    hidden = ("https://store.steampowered.com/app/9",)
    assert source_links("Подписаться", hidden) == (SourceLink("steam", "9", TitleKind.GAME),)
    assert source_links(text, ("https://shikimori.one/animes/20",))[0].ref == "20"  # an entity and the text: one link
    assert len(source_links(text, ("https://shikimori.one/animes/20",))) == 2
    assert names("Подписаться", links=hidden) == []  # a hidden link is never a name


def test_a_trailing_mark_is_cut_and_a_bare_domain_in_the_text_is_not_read():
    assert source_links("", ("https://themoviedb.org/movie/550).",))[0].ref == "550"
    assert source_links("см. themoviedb.org/movie/550 тут") == ()  # such a link comes with its entity


# --- query ----------------------------------------------------------------------------------------------------------


def test_the_query_of_an_item_is_the_first_candidate():
    assert query_of(samples()[1]) == "Ghost in the SQL Data"
    assert query_of(samples()[2]) == "Dead-End Job"
    assert query_of("Блич", forwarded=True) == "Блич"
    assert query_of(later("Текст без названий"), bold=("Игра года",)) == "Игра года"


def test_without_candidates_the_query_is_the_beginning_of_the_text():
    assert candidates("Steam") == []
    assert query_of("Steam") == "Steam"
    assert query_of("") == ""
    long = " ".join(["Слово"] * 20)
    assert text_query(long) == "Слово Слово Слово Слово Слово Слово Слово Слово Слово Слово"
    assert text_query("я" * 100) == "я" * 60
    assert text_query("  Дюна:\n  Часть  вторая ") == "Дюна: Часть вторая"
    assert text_query("Дюна") == "Дюна"
