"""The health check for Docker (`python -m app.healthcheck`, KI-3): asks the application's own `/health`.

Exit code 0 only on an answer 200; otherwise 1 and one line with the reason (Docker keeps it in `docker inspect`).
Standard library only and no settings: it starts fast and does not read `.env`.
"""

import sys
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8080/health"
TIMEOUT_SECONDS = 5


def check(url: str = URL, timeout: float = TIMEOUT_SECONDS) -> str | None:
    """None when healthy, otherwise the reason in one line."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return None if response.status == 200 else f"/health ответил {response.status}"
    except urllib.error.HTTPError as exc:
        return f"/health ответил {exc.code}"
    except Exception as exc:  # refused, timeout, a broken answer: all mean "not healthy"
        return f"/health не отвечает: {exc!r}"


def main() -> int:
    reason = check()
    if reason:
        print(reason, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
