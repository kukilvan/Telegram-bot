"""`.env.example` lists every variable the code reads and no other (KI-49): the fields of `Settings`, the names of
`docker-compose.yml` and the names `app/container_start.py` reads. A line may be commented out; the names are the
words before `=`."""

import re
from pathlib import Path

from app.config import Settings
from app.container_start import ID_NAMES

ROOT = Path(__file__).resolve().parent.parent
LINE = re.compile(r"^#? ?([A-Z][A-Z0-9_]*)=", re.MULTILINE)
INTERNAL = {"ALLOWED_TELEGRAM_USER_IDS_RAW"}  # the second spelling of a field: the owner writes the first


def listed(text: str) -> set[str]:
    return set(LINE.findall(text))


def read_by_the_code() -> set[str]:
    names = set()
    for key, field in Settings.model_fields.items():
        alias = field.validation_alias
        names.add(alias.choices[0] if alias is not None else key.upper())
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    names.update(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", compose))
    names.update(ID_NAMES)
    return names - INTERNAL


def test_env_example_lists_every_name_the_code_reads_and_none_other():
    expected = read_by_the_code()
    found = listed((ROOT / ".env.example").read_text(encoding="utf-8"))
    assert expected - found == set(), "missing from .env.example"
    assert found - expected == set(), "named in .env.example, read by nobody"


def test_the_names_the_code_reads_are_the_ones_of_the_owner():
    names = read_by_the_code()
    assert {"TELEGRAM_BOT_TOKEN", "ALLOWED_TELEGRAM_USER_IDS", "SHIKIMORI_BASE_URL", "SHIKIMORI_USER_AGENT", "WEB_PORT",
            "WEB_HOST", "PUID", "PGID"} <= names
    assert "ALLOWED_TELEGRAM_USER_IDS_RAW" not in names


def test_the_check_fails_for_a_missing_and_for_an_alien_name():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    expected = read_by_the_code()
    assert "TMDB_API_KEY" in listed(text)
    assert expected - listed(text.replace("TMDB_API_KEY=", "# nothing=")) == {"TMDB_API_KEY"}
    assert listed(text + "\nKINOPUB_ACCESS_TOKEN=x\n") - expected == {"KINOPUB_ACCESS_TOKEN"}
