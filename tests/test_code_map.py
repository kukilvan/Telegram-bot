"""The code map is built from the docstrings: the committed file is the built one, and every module describes itself."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("code_map", ROOT / "tools" / "code_map.py")
code_map = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(code_map)

RUN = r"run .venv\Scripts\python.exe tools\code_map.py"


def test_the_committed_map_is_the_built_one():
    current = (ROOT / "docs" / "code-map.md").read_text(encoding="utf-8")

    assert code_map.rewrite(current, code_map.render(code_map.modules())) == current, f"docs/code-map.md is out of date: {RUN}"


def test_every_module_of_the_app_describes_itself():
    listed = code_map.modules()

    assert [path for path, text in listed if not text] == [], "these modules have no docstring"
    assert [path for path, text in listed if len(text) > code_map.MAX_SUMMARY] == [], (
        f"the first sentence of these docstrings is over {code_map.MAX_SUMMARY} characters: it is the line of the map"
    )


def test_the_map_has_a_line_for_a_module_of_every_folder_of_the_app():
    folders = {path.rsplit("/", 1)[0] for path, _ in code_map.modules()}

    assert {"app", "app/bot", "app/providers", "app/tracker", "app/tracker/pollers", "app/tracker/sources", "app/utils", "app/web"} <= folders


def test_a_description_is_the_first_sentence_on_one_line():
    source = '"""Reads the dates of a game from the\nsnapshot of IGDB. Then something else.\n\nA second paragraph."""\nx = 1\n'

    assert code_map.summary(source) == "Reads the dates of a game from the snapshot of IGDB."


def test_a_description_does_not_stop_at_a_period_inside_a_word_or_a_number():
    source = '"""Throttling of Phase 7.5 and the file `a.py` in the «Скоро» block, e.g. for AniList."""\n'

    assert code_map.summary(source) == "Throttling of Phase 7.5 and the file `a.py` in the «Скоро» block, e.g. for AniList."


def test_a_module_without_a_docstring_has_no_description():
    assert code_map.summary("x = 1\n") is None
    assert code_map.render([("app/x.py", None)]) == "- `app/x.py` — (no docstring)"


def test_only_the_part_between_the_markers_is_rewritten():
    text = f"before\n{code_map.START}\nold line\n{code_map.END}\nafter\n"

    assert code_map.rewrite(text, "new line") == f"before\n{code_map.START}\nnew line\n{code_map.END}\nafter\n"


def test_a_map_without_markers_is_refused():
    with pytest.raises(ValueError):
        code_map.rewrite("no markers here\n", "x")
