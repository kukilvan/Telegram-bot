"""Start of the container (`python -m app.container_start`, KI-4).

The container starts as root only to fix the rights on the mounted `data` folder, then drops them and replaces itself
with the application (`python -m app.main`). Everything here is Python, not a shell script: GitHub Desktop may rewrite
line endings and a shell script would then not start in Linux. The module imports on Windows (the tests run there):
changing the user and the like are done only inside the start function; paths are passed to the pure functions.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

APP_DIR = Path("/app")
DATA_DIR = APP_DIR / "data"
ZONEINFO_DIR = Path("/usr/share/zoneinfo")
DEFAULT_ID = 1000
APP_COMMAND = [sys.executable, "-m", "app.main"]

BAD_ID_MESSAGE = ("PUID и PGID должны быть числами (номера пользователя и группы на компьютере, "
                  "где лежит папка data)")
ROOT_WARNING = "PUID или PGID равен 0: приложение работает от root"


class StartError(Exception):
    """A start problem the owner can fix; the text is for them."""


@dataclass(frozen=True)
class Identity:
    uid: int
    gid: int


def read_identity(environ: Mapping[str, str]) -> Identity:
    """PUID and PGID from the environment (1000 by default). Not a whole number or below zero is an error."""
    numbers = []
    for name in ("PUID", "PGID"):
        text = environ.get(name, "").strip()
        if not text:
            numbers.append(DEFAULT_ID)
            continue
        try:
            number = int(text)
        except ValueError:
            raise StartError(BAD_ID_MESSAGE) from None
        if number < 0:
            raise StartError(BAD_ID_MESSAGE)
        numbers.append(number)
    return Identity(uid=numbers[0], gid=numbers[1])


def paths_to_hand_over(data_dir: Path, identity: Identity, *, walk: Callable[[Path], list[Path]] | None = None,
                       stat_owner: Callable[[Path], tuple[int, int]] | None = None) -> list[Path]:
    """The folder itself and everything in it whose owner is not `identity`."""
    walk = walk or _walk
    stat_owner = stat_owner or _stat_owner
    wanted = (identity.uid, identity.gid)
    found = []
    for path in [data_dir, *walk(data_dir)]:
        try:
            owner = stat_owner(path)
        except OSError:
            continue
        if owner != wanted:
            found.append(path)
    return found


def _walk(top: Path) -> list[Path]:
    return list(top.rglob("*"))


def _stat_owner(path: Path) -> tuple[int, int]:
    info = path.lstat()
    return info.st_uid, info.st_gid


def hand_over(paths: list[Path], identity: Identity, chown: Callable[..., None] | None = None) -> None:
    """Give the paths to `identity`. A refusal is skipped: Docker Desktop on Windows does not allow or keep it,
    and writing there is allowed to everyone."""
    chown = chown or _chown
    for path in paths:
        try:
            chown(path, identity.uid, identity.gid)
        except OSError:
            pass


def _chown(path: Path, uid: int, gid: int) -> None:
    os.chown(path, uid, gid, follow_symlinks=False)


def choose_tz(environ: Mapping[str, str], zoneinfo_dir: Path = ZONEINFO_DIR) -> tuple[str | None, str | None]:
    """(TZ to set or None, warning or None). TZ already set stays; BOT_TIMEZONE without a file in the zone
    database is a warning and UTC."""
    if environ.get("TZ", "").strip():
        return None, None
    name = environ.get("BOT_TIMEZONE", "").strip()
    if not name:
        return None, None
    candidate = zoneinfo_dir / name
    if ".." in Path(name).parts or not candidate.is_file():
        return None, f"BOT_TIMEZONE={name}: такого пояса нет в системе, журнал будет по UTC"
    return name, None


def write_refusal_message(path: Path, identity: Identity, owner: tuple[int, int] | None) -> str:
    who = f"{owner[0]}:{owner[1]}" if owner else "неизвестен"
    return (f"Нет прав на запись в папку {path} (её владелец {who}, приложение работает как "
            f"{identity.uid}:{identity.gid}). На NAS задайте в .env PUID и PGID — номера владельца папки")


def check_writable(folders: list[Path], identity: Identity) -> None:
    """Create and remove a trial file in each folder; a refusal is a clear error."""
    for folder in folders:
        probe = folder / f".write-check-{os.getpid()}"
        try:
            probe.write_bytes(b"")
            probe.unlink()
        except OSError:
            try:
                owner = _stat_owner(folder)
            except OSError:
                owner = None
            raise StartError(write_refusal_message(folder, identity, owner)) from None


def app_command() -> list[str]:
    return list(APP_COMMAND)


def _make_folders(data_dir: Path) -> None:
    for folder in (data_dir, data_dir / "backups", data_dir / "logs"):
        folder.mkdir(parents=True, exist_ok=True)


def start(environ: Mapping[str, str] = os.environ, data_dir: Path = DATA_DIR, zoneinfo_dir: Path = ZONEINFO_DIR) -> None:
    """Prepare the folders and the rights, then become the application. Does not return."""
    is_root = os.geteuid() == 0
    identity = read_identity(environ)
    if is_root and 0 in (identity.uid, identity.gid):
        print(ROOT_WARNING, flush=True)
    try:
        _make_folders(data_dir)
    except OSError:
        pass  # the write check below says what is wrong
    if is_root:
        hand_over(paths_to_hand_over(data_dir, identity), identity)
    new_tz, warning = choose_tz(environ, zoneinfo_dir)
    if warning:
        print(warning, flush=True)
    if new_tz:
        os.environ["TZ"] = new_tz
    if is_root:
        os.environ["HOME"] = "/tmp"
        os.setgroups([])
        os.setgid(identity.gid)
        os.setuid(identity.uid)
    check_writable([data_dir, data_dir / "logs"], identity)
    command = app_command()
    os.execv(command[0], command)


def main() -> int:
    try:
        start()
    except StartError as exc:
        print(exc, file=sys.stderr, flush=True)
        return 1
    return 0  # not reached: `start` replaces the process


if __name__ == "__main__":
    sys.exit(main())
