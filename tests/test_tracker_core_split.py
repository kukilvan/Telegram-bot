"""The core is split into modules behind one facade (docs/coding-standards.md, rule 7).

These tests guard the shape: `core.py` only assembles and passes calls on, no module grows past its limit, the kind of a
title is chosen in one table, and the pure modules stay free of the database. The behaviour itself is covered by the
tests of the core.
"""

import ast
import inspect
from pathlib import Path

import pytest

from app.tracker import core, kinds, polling
from app.tracker.models import TitleKind
from app.tracker.pollers.base import Poller

TRACKER = Path(core.__file__).parent
MODULES = ("context", "settings_store", "storage", "queue", "titles", "polling", "delivery_service", "test_samples", "core")
POLLERS = sorted((TRACKER / "pollers").glob("*.py"))
PURE = ("dedup", "delivery", "movie_events", "series_events", "anime_events", "sequel_events", "seasons", "progress", "failures", "cards", "kinds")
MAX_LINES = 400


def lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def imported_names(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


@pytest.mark.parametrize("path", [TRACKER / f"{name}.py" for name in MODULES] + POLLERS, ids=lambda p: p.name)
def test_no_part_of_the_core_is_longer_than_the_limit(path):
    assert lines(path) <= MAX_LINES


def test_the_facade_holds_only_assembly_and_hand_overs():
    source = (TRACKER / "core.py").read_text(encoding="utf-8")
    sqlalchemy_names = {name for name in imported_names(TRACKER / "core.py") if name.startswith("sqlalchemy")}

    assert sqlalchemy_names <= {"sqlalchemy.orm"}  # only the type of the session factory it is given
    assert "select(" not in source and ".execute(" not in source and "session." not in source


def test_every_public_method_of_the_facade_but_the_two_without_a_database_is_a_coroutine():
    # after the split no facade method names `session_factory`, so the source search of the async-interface test finds
    # nothing; this keeps rule 1 guarded by the type of the method itself
    ordinary = [
        name
        for name, method in inspect.getmembers(core.Tracker, predicate=inspect.isfunction)
        if not name.startswith("_") and not inspect.iscoroutinefunction(method)
    ]

    assert sorted(ordinary) == ["register_test_sample", "test_samples"]


def test_every_public_call_of_the_facade_is_handed_to_a_part():
    for name, method in inspect.getmembers(core.Tracker, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        body = inspect.getsource(method).split('"""')[-1]  # what follows the docstring
        assert "self._" in body, name


def test_the_core_does_not_ask_which_kind_a_title_is():
    offenders = []
    for path in [TRACKER / f"{name}.py" for name in MODULES if name not in ("polling",)] + POLLERS:
        for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = text.split("#")[0]
            if "TitleKind." in code and ("==" in code or "!=" in code or " in " in code or "{" in code):
                offenders.append(f"{path.name}:{number}")
    assert offenders == []


def test_every_kind_has_one_poller_with_the_same_set_of_actions():
    assert set(polling.POLLER_CLASSES) == set(TitleKind) == set(kinds.KINDS)
    for kind, poller_class in polling.POLLER_CLASSES.items():
        assert issubclass(poller_class, Poller), kind
        for action in ("first_seasons", "first_check", "store_extras", "apply"):
            assert callable(getattr(poller_class, action)), (kind, action)


def test_the_pure_modules_know_nothing_of_the_database():
    for name in PURE:
        names = imported_names(TRACKER / f"{name}.py")  # `failures` reads httpx errors, but makes no call
        assert not {n for n in names if n.startswith(("sqlalchemy", "app.tracker.db", "app.providers"))}, name


def test_the_public_names_of_the_core_stay_importable_from_the_facade():
    for name in (
        "Tracker", "TestSample", "TitleNotFound", "UnknownEvent", "UnknownKind", "UnknownSeason", "UnknownTitle",
        "TitleSummary", "WatchableSeason", "AddResult", "DeleteResult", "WatchedResult", "SummaryResult",
        "TestEventResult", "DeliveryReport", "PollReport",
    ):
        assert hasattr(core, name), name
