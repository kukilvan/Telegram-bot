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

def test_compose_publishes_the_port_only_on_this_pc_and_mounts_only_data():
    compose = _text("docker-compose.yml")

    assert '"127.0.0.1:${WEB_PORT:-8080}:8080"' in compose
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
    assert 'HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 CMD ["python", "-m", "app.healthcheck"]' in dockerfile
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
    assert "app\\.(bot\\.)?main" in script  # the old bot from .venv is only stopped
    assert "python.exe -m" not in script and "Activate.ps1" not in script and "Scripts\\python" not in script
    assert "WEB_PORT=8081" in script and "http://localhost:" in script
    assert "E:\\" not in script
    assert not (ROOT / "launch_bot.py").exists()


def test_stop_and_logs_scripts_call_compose_from_any_folder():
    stop = _script("stop-bot.ps1")
    logs = _script("logs-bot.ps1")

    assert "Set-Location $PSScriptRoot" in stop and "docker compose down" in stop
    assert "Set-Location $PSScriptRoot" in logs and "docker compose logs -f --tail 100" in logs
    assert "продолжает работать" in logs


def test_env_example_has_the_docker_settings():
    example = _text(".env.example")

    for line in ("WEB_PORT=8080", "PUID=1000", "PGID=1000"):
        assert line in example
