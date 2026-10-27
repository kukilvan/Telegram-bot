"""The start of the container: PUID/PGID, who gets the data folder, TZ, the write check and the command."""

import os
import sys
from pathlib import Path

import pytest

from app import container_start as cs
from app.container_start import Identity, StartError


# ---- PUID / PGID ----------------------------------------------------------

def test_puid_and_pgid_default_to_1000():
    assert cs.read_identity({}) == Identity(1000, 1000)
    assert cs.read_identity({"PUID": " ", "PGID": ""}) == Identity(1000, 1000)


def test_puid_and_pgid_are_read_from_the_environment():
    assert cs.read_identity({"PUID": "1026", "PGID": "100"}) == Identity(1026, 100)
    assert cs.read_identity({"PUID": "0", "PGID": "0"}) == Identity(0, 0)


@pytest.mark.parametrize("environ", [{"PUID": "abc"}, {"PGID": "1.5"}, {"PUID": "-1"}, {"PGID": "-7"}])
def test_garbage_in_puid_or_pgid_is_a_clear_error(environ):
    with pytest.raises(StartError, match="PUID и PGID должны быть числами"):
        cs.read_identity(environ)


# ---- who gets the folder --------------------------------------------------

def test_only_paths_with_another_owner_are_handed_over():
    data = Path("/app/data")
    owners = {
        data: (0, 0), data / "tracker.db": (1000, 1000), data / "logs": (0, 0), data / "logs/bot.log": (1000, 0),
    }

    found = cs.paths_to_hand_over(
        data, Identity(1000, 1000), walk=lambda top: [p for p in owners if p != top], stat_owner=owners.__getitem__,
    )

    assert found == [data, data / "logs", data / "logs/bot.log"]


def test_a_path_that_vanished_while_looking_is_skipped():
    data = Path("/app/data")

    def stat_owner(path):
        if path.name == "gone":
            raise FileNotFoundError(path)
        return (0, 0)

    found = cs.paths_to_hand_over(data, Identity(1000, 1000), walk=lambda top: [data / "gone", data / "x"],
                                  stat_owner=stat_owner)

    assert found == [data, data / "x"]


def test_a_refused_change_of_owner_does_not_stop_the_rest():
    calls = []

    def chown(path, uid, gid):
        calls.append(path)
        if path.name == "a":
            raise PermissionError(path)

    cs.hand_over([Path("a"), Path("b")], Identity(1, 2), chown=chown)

    assert calls == [Path("a"), Path("b")]


def test_the_real_walk_finds_nested_paths(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "bot.log").write_text("x")
    me = (os.getuid(), os.getgid()) if hasattr(os, "getuid") else None
    if me is None:
        pytest.skip("no owners on Windows")

    assert cs.paths_to_hand_over(tmp_path, Identity(*me)) == []
    assert tmp_path / "logs" / "bot.log" in cs.paths_to_hand_over(tmp_path, Identity(me[0] + 1, me[1]))


# ---- TZ -------------------------------------------------------------------

def test_tz_follows_bot_timezone_when_the_zone_exists(tmp_path):
    (tmp_path / "Europe").mkdir()
    (tmp_path / "Europe" / "Moscow").write_text("zone")

    assert cs.choose_tz({"BOT_TIMEZONE": "Europe/Moscow"}, tmp_path) == ("Europe/Moscow", None)


def test_an_unknown_zone_warns_and_leaves_utc(tmp_path):
    tz, warning = cs.choose_tz({"BOT_TIMEZONE": "Mars/Olympus"}, tmp_path)

    assert tz is None and "Mars/Olympus" in warning and "UTC" in warning


def test_a_zone_that_climbs_out_of_the_zone_folder_is_unknown(tmp_path):
    (tmp_path / "secret").write_text("x")
    zones = tmp_path / "zones"
    zones.mkdir()

    assert cs.choose_tz({"BOT_TIMEZONE": "../secret"}, zones)[0] is None


def test_tz_that_is_already_set_stays_and_no_timezone_means_nothing_to_do(tmp_path):
    assert cs.choose_tz({"TZ": "Asia/Tokyo", "BOT_TIMEZONE": "Europe/Moscow"}, tmp_path) == (None, None)
    assert cs.choose_tz({}, tmp_path) == (None, None)
    assert cs.choose_tz({"BOT_TIMEZONE": " "}, tmp_path) == (None, None)


# ---- write check ----------------------------------------------------------

def test_a_writable_folder_passes_and_leaves_no_trial_file(tmp_path):
    cs.check_writable([tmp_path], Identity(1000, 1000))

    assert list(tmp_path.iterdir()) == []


def test_a_folder_that_refuses_writes_gives_the_owner_a_clear_message(tmp_path):
    missing = tmp_path / "nope"

    with pytest.raises(StartError) as caught:
        cs.check_writable([missing], Identity(1000, 1000))

    text = str(caught.value)
    assert "Нет прав на запись в папку" in text and "приложение работает как 1000:1000" in text
    assert "PUID и PGID" in text and "неизвестен" in text


def test_the_refusal_message_names_the_owner_of_the_folder():
    text = cs.write_refusal_message(Path("/app/data"), Identity(1000, 1000), (1026, 100))

    assert "её владелец 1026:100" in text


# ---- the command ----------------------------------------------------------

def test_the_container_replaces_itself_with_the_one_process_app():
    assert cs.app_command() == [sys.executable, "-m", "app.main"]


def test_start_makes_the_folders_checks_and_executes_the_application(tmp_path, monkeypatch):
    executed = []
    monkeypatch.setattr(cs.os, "execv", lambda path, argv: executed.append((path, argv)), raising=False)
    monkeypatch.setattr(cs.os, "geteuid", lambda: 1000, raising=False)  # not root: no change of owner or user
    monkeypatch.delenv("TZ", raising=False)
    zones = tmp_path / "zones"
    (zones / "Europe").mkdir(parents=True)
    (zones / "Europe" / "Moscow").write_text("zone")

    cs.start({"BOT_TIMEZONE": "Europe/Moscow"}, data_dir=tmp_path / "data", zoneinfo_dir=zones)

    assert (tmp_path / "data" / "backups").is_dir() and (tmp_path / "data" / "logs").is_dir()
    assert executed == [(sys.executable, [sys.executable, "-m", "app.main"])]
    assert os.environ["TZ"] == "Europe/Moscow"
    monkeypatch.delenv("TZ")


def test_start_as_root_drops_the_rights_after_handing_over_the_folder(tmp_path, monkeypatch):
    steps = []
    monkeypatch.setattr(cs.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(cs.os, "setgroups", lambda groups: steps.append(("setgroups", groups)), raising=False)
    monkeypatch.setattr(cs.os, "setgid", lambda gid: steps.append(("setgid", gid)), raising=False)
    monkeypatch.setattr(cs.os, "setuid", lambda uid: steps.append(("setuid", uid)), raising=False)
    monkeypatch.setattr(cs, "hand_over", lambda paths, identity, chown=None: steps.append(("chown", identity)))
    monkeypatch.setattr(cs.os, "execv", lambda path, argv: steps.append(("exec", argv)), raising=False)
    monkeypatch.setenv("HOME", "/root")

    cs.start({"PUID": "1026", "PGID": "100"}, data_dir=tmp_path / "data", zoneinfo_dir=tmp_path)

    assert [step[0] for step in steps] == ["chown", "setgroups", "setgid", "setuid", "exec"]
    assert steps[1:4] == [("setgroups", []), ("setgid", 100), ("setuid", 1026)]
    assert os.environ["HOME"] == "/tmp"


def test_main_prints_the_error_and_exits_with_1(monkeypatch, capsys):
    def refuse():
        raise StartError("нельзя")

    monkeypatch.setattr(cs, "start", refuse)

    assert cs.main() == 1
    assert "нельзя" in capsys.readouterr().err


def test_the_module_imports_without_posix_only_calls():
    # the tests run on Windows too: setuid and the like may only be called inside `start`
    source = Path(cs.__file__).read_text(encoding="utf-8")
    top_level = source.split("def start(")[0]

    assert "os.setuid" not in top_level and "os.geteuid" not in top_level
