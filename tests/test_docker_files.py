"""The files that make the Docker image and start it: compose, Dockerfile, .dockerignore and the owner's scripts."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOM = b"\xef\xbb\xbf"


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _script(name: str) -> str:
    raw = (ROOT / name).read_bytes()
    assert raw.startswith(BOM)  # with BOM, or Windows PowerShell 5.1 garbles the Russian text
    return raw.decode("utf-8-sig")


# ---- docker-compose.yml ---------------------------------------------------

def test_compose_publishes_the_port_only_on_this_pc_unless_the_owner_opens_it_and_mounts_only_data():
    compose = _text("docker-compose.yml")

    assert '"${WEB_HOST:-127.0.0.1}:${WEB_PORT:-8080}:8080"' in compose  # closed by default (ADR 0008)
    assert len(re.findall(r"^\s+- \./", compose, re.MULTILINE)) == 1
    assert "./data:/app/data" in compose
    assert "./logs" not in compose


def test_compose_has_no_version_no_pgrep_and_waits_for_a_stop():
    compose = _text("docker-compose.yml")

    assert not re.search(r"^version:", compose, re.MULTILINE)
    assert "pgrep" not in compose and "healthcheck" not in compose  # the check is in the Dockerfile
    assert "stop_grace_period: 45s" in compose  # the stop takes at most about 31 s (KI-9)
    assert "init: true" in compose  # the app is a child of the init: the health check can end it (KI-6, ADR 0015)
    assert 'max-size: "10m"' in compose and 'max-file: "3"' in compose
    assert "restart: unless-stopped" in compose
    assert "env_file: .env" in compose


def test_the_override_example_mounts_only_the_copies_folder_and_the_real_override_is_ignored():
    example = _text("docker-compose.override.example.yml")
    mounts = re.findall(r"^\s+- (\S+)", example, re.MULTILINE)

    assert len(mounts) == 1 and mounts[0].endswith(":/app/data/backups")
    assert "services:\n  tracker:\n    volumes:" in example.replace("\r\n", "\n")
    assert "docker-compose.override.yml" in _text(".gitignore").split()  # the real one stays out of git


def test_compose_itself_still_mounts_only_data_so_the_pc_is_unchanged():
    assert re.findall(r"^\s+- (\./\S+|/\S+:\S+)", _text("docker-compose.yml"), re.MULTILINE) == ["./data:/app/data"]


# ---- Dockerfile -----------------------------------------------------------

def test_dockerfile_starts_as_root_and_checks_health_with_python():
    dockerfile = _text("Dockerfile")

    assert not re.search(r"^USER\b", dockerfile, re.MULTILINE)
    assert "pgrep" not in dockerfile and "curl" not in dockerfile
    assert 'HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --start-interval=2s --retries=3 CMD ["python", "-m", "app.healthcheck"]' in dockerfile
    assert 'CMD ["python", "-m", "app.container_start"]' in dockerfile
    assert "WEB_BIND_HOST=0.0.0.0" in dockerfile and "PYTHONUNBUFFERED=1" in dockerfile
    assert "EXPOSE 8080" in dockerfile
    assert ".sh" not in dockerfile


def test_dockerfile_starts_with_the_syntax_line_for_an_older_docker():
    # BuildKit then takes this Dockerfile frontend, which knows `--start-interval` (7.3.02), pinned by its digest
    first = _text("Dockerfile").splitlines()[0]

    assert re.fullmatch(r"# syntax=docker/dockerfile:1\.\d+@sha256:[0-9a-f]{64}", first), first


def test_the_base_image_is_pinned_by_an_exact_tag_and_its_digest():
    # two builds of one commit on different days get the same system and Python (the NAS project's question 3)
    bases = re.findall(r"^FROM (\S+)", _text("Dockerfile"), re.MULTILINE)

    assert len(bases) == 1 and re.fullmatch(r"python:3\.12\.\d+-slim@sha256:[0-9a-f]{64}", bases[0]), bases


def _lock() -> dict[str, tuple[str, int]]:
    """requirements.lock as name -> (version, number of hashes), names in lower case with `-`."""
    pinned: dict[str, tuple[str, int]] = {}
    name = ""
    for line in _text("requirements.lock").splitlines():
        found = re.match(r"^([A-Za-z0-9_.-]+)==(\S+)", line)
        if found:
            name = found.group(1).lower().replace("_", "-")
            pinned[name] = (found.group(2), 0)
        elif line.strip().startswith("--hash=sha256:"):
            version, hashes = pinned[name]
            pinned[name] = (version, hashes + 1)
    return pinned


def test_the_image_installs_only_the_lock_with_hashes():
    dockerfile = _text("Dockerfile")

    assert "COPY requirements.lock ." in dockerfile
    assert "pip install --no-cache-dir --require-hashes -r requirements.lock" in dockerfile
    assert "requirements.txt" not in dockerfile
    assert "requirements.lock" not in set(_text(".dockerignore").split())


def test_every_package_of_the_lock_is_exact_and_hashed():
    lock = _lock()
    text = _text("requirements.lock")

    assert len(lock) > 20
    assert not re.search(r"^[A-Za-z0-9_.-]+\s*(>=|<=|~=|>|<|!=)", text, re.MULTILINE)  # only `==`
    assert all(hashes for _, hashes in lock.values()), [name for name, (_, hashes) in lock.items() if not hashes]


def test_the_lock_holds_every_requirement_within_its_range():
    from packaging.requirements import Requirement

    lock = _lock()
    for line in _text("requirements.txt").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        wanted = Requirement(line)
        name = wanted.name.lower().replace("_", "-")
        assert name in lock, name
        assert wanted.specifier.contains(lock[name][0]), (name, lock[name][0], str(wanted.specifier))


def test_there_are_no_shell_scripts_to_run_in_the_container():
    assert not list((ROOT / "app").rglob("*.sh"))


# ---- .dockerignore --------------------------------------------------------

def test_the_image_gets_no_secrets_data_or_tests():
    ignored = set(_text(".dockerignore").split())

    for name in (".env", "data/", "tests/", "docs/", ".scratch/", "*.md", ".venv", ".git", "app/logs/", "*.ps1",
                 "test_*.py", "*.egg-info", "PROMPT.txt", "opencode.json"):
        assert name in ignored, name


# ---- scripts --------------------------------------------------------------

def test_start_script_builds_and_raises_the_container_without_python():
    script = _script("start-bot.ps1")

    assert "Set-Location $PSScriptRoot" in script
    assert "docker compose up -d --build" in script
    assert "docker info" in script and "Test-Path \".env\"" in script
    assert "python.exe -m" not in script and "Activate.ps1" not in script  # never starts the bot itself, only stops an old one
    assert "WEB_PORT=8081" in script and "http://localhost:" in script
    assert "E:\\" not in script
    assert not (ROOT / "launch_bot.py").exists()


def _old_bot_pattern() -> re.Pattern:
    """The pattern that picks the old bot's processes, taken from the script itself: the test checks what it says."""
    # `\r?`: a checkout on Windows has CRLF line ends, and `$` does not match before `\r` (review 9.1a)
    found = re.search(r"^\$oldBotPattern = '(.*)'\r?$", _script("start-bot.ps1"), re.MULTILINE)
    assert found
    return re.compile(found.group(1))


def test_the_start_script_stops_only_the_old_bot_by_the_whole_command():
    pattern = _old_bot_pattern()

    for ours in (r"python -m app.bot.main", r'"C:\x\.venv\Scripts\python.exe" -m app.main', r"python.exe -m app.main --x",
                 r'"python.exe" -m app.bot.main'):
        assert pattern.search(ours), ours
    for foreign in (r"python -m uvicorn app.main:app", r"python -m app.mainframe", r"python -m myapp.main",
                    r"python -m app.bot.mainframe", r"python app\main.py"):
        assert not pattern.search(foreign), foreign


def test_the_start_script_stops_only_this_projects_old_bot_and_its_children():
    script = _script("start-bot.ps1")

    assert '$ownPython = Join-Path $PSScriptRoot ".venv\\Scripts\\python.exe"' in script
    assert "$_.ExecutablePath -ieq $ownPython" in script  # the whole path, any case, the folder of the script itself
    assert "$_.CommandLine -match $oldBotPattern" in script
    assert "$old.ProcessId -contains $_.ParentProcessId" in script  # the python.exe the .venv one starts
    # ... with the same command: a stranger whose dead parent had the old bot's id (ids are reused) is left alone
    assert "($old.ProcessId -contains $_.ParentProcessId) -and ($_.CommandLine -match $oldBotPattern)" in script
    assert script.index("$ownPython") < script.index("Stop-Process") < script.index("docker compose up -d --build")
    assert "Остановлен старый бот, запущенный не через Docker" in script
    # the old test of the pattern alone would stop any project's `-m app.main`: the stop list is filtered by the path
    assert "Where-Object { $_.CommandLine -match $oldBotPattern })" not in script


def test_the_start_script_waits_for_the_outcome_by_the_clock_not_by_the_number_of_checks():
    script = _script("start-bot.ps1")

    assert "$deadline = (Get-Date).AddSeconds(90)" in script
    assert "while ((Get-Date) -lt $deadline) {" in script  # the last check starts before the deadline
    assert "Start-Sleep -Seconds 2" in script  # a pause of 2 s between the checks
    assert "$waited" not in script and "-le 90" not in script
    assert script.index("$deadline") < script.index("Get-ContainerState", script.index("$deadline"))
    assert "Жду запуска приложения (до 90 секунд)" in script and "запускается дольше обычного" in script


def test_the_start_script_refuses_a_dollar_in_env_without_printing_the_value():
    script = _script("start-bot.ps1")
    check, build = script.index("Contains('$')"), script.index("docker compose up -d --build")

    assert check < script.index("$oldBotPattern") < build  # before anything is stopped or built
    assert "Get-Content \".env\"" in script and 'StartsWith("#")' in script
    assert "$lineNumber ($name)" in script  # the number and the name of the setting
    for written in re.findall(r"^\s*Write-Host .*$", script[check:build], re.MULTILINE):
        assert "$envLine" not in written  # the line itself is never written out, only its number and the name


def test_the_start_script_shows_the_build_as_it_goes_and_waits_for_the_outcome():
    script = _script("start-bot.ps1")

    assert "$output = docker compose up" not in script  # the whole output is not held until the end
    assert "docker compose up -d --build 2>&1 | ForEach-Object {" in script and "Write-Host $text" in script
    assert 'docker compose ps -q tracker' in script and "docker inspect" in script
    assert 'eq "healthy"' in script and "RestartCount" in script and "90" in script
    assert "docker compose logs --no-color --tail 30 tracker" in script
    assert "Запуск не удался" in script and "запускается дольше обычного" in script
    assert "Готово. Бот работает в Docker. Приложение: http://localhost:$port" in script
    assert "токен бота неверного вида" in script and "Внимание: бот не подключён к Telegram" in script


def test_the_hint_about_the_token_looks_for_the_words_the_application_logs():
    from app.bot.tracker_handlers import MALFORMED_TOKEN

    assert MALFORMED_TOKEN.startswith("токен бота неверного вида")
    assert "токен бота неверного вида" in _script("start-bot.ps1")


def test_stop_and_logs_scripts_call_compose_from_any_folder():
    stop = _script("stop-bot.ps1")
    logs = _script("logs-bot.ps1")

    assert "Set-Location $PSScriptRoot" in stop and "docker compose down" in stop
    assert "Set-Location $PSScriptRoot" in logs and "docker compose logs -f --tail 100" in logs
    assert "продолжает работать" in logs


def test_env_example_has_the_docker_settings():
    example = _text(".env.example")

    for line in ("WEB_PORT=8080", "WEB_HOST=127.0.0.1", "PUID=1000", "PGID=1000"):
        assert line in example


def test_env_example_warns_about_the_dollar_sign():
    example = _text(".env.example")

    assert "Не используйте в значениях знак $" in example
    password_comment = example.split("WEB_PASSWORD=")[0].splitlines()[-1]
    assert "без знака $" in password_comment
