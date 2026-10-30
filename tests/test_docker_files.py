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
    assert "stop_grace_period: 30s" in compose
    assert 'max-size: "10m"' in compose and 'max-file: "3"' in compose
    assert "restart: unless-stopped" in compose
    assert "env_file: .env" in compose


# ---- Dockerfile -----------------------------------------------------------

def test_dockerfile_starts_as_root_and_checks_health_with_python():
    dockerfile = _text("Dockerfile")

    assert not re.search(r"^USER\b", dockerfile, re.MULTILINE)
    assert "pgrep" not in dockerfile and "curl" not in dockerfile
    assert 'HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --start-interval=2s --retries=3 CMD ["python", "-m", "app.healthcheck"]' in dockerfile
    assert 'CMD ["python", "-m", "app.container_start"]' in dockerfile
    assert "WEB_BIND_HOST=0.0.0.0" in dockerfile and "PYTHONUNBUFFERED=1" in dockerfile
    assert "EXPOSE 8080" in dockerfile
    assert "python:3.12-slim" in dockerfile
    assert ".sh" not in dockerfile


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
    assert "python.exe -m" not in script and "Activate.ps1" not in script and "Scripts\\python" not in script
    assert "WEB_PORT=8081" in script and "http://localhost:" in script
    assert "E:\\" not in script
    assert not (ROOT / "launch_bot.py").exists()


def _old_bot_pattern() -> re.Pattern:
    """The pattern that picks the old bot's processes, taken from the script itself: the test checks what it says."""
    found = re.search(r"^\$oldBotPattern = '(.*)'$", _script("start-bot.ps1"), re.MULTILINE)
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
