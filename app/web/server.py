"""uvicorn for the runtime (`app/runtime.py`): no signal handling and no logging setup of its own."""

import contextlib
from collections.abc import Iterator, Sequence

import uvicorn
from fastapi import FastAPI


class _Server(uvicorn.Server):
    """uvicorn whose signal handling is off: only the runtime catches SIGTERM / SIGINT. Otherwise uvicorn, catching
    them itself, would stop the web alone and, once done, send the caught signal to the process again. The way to
    switch it off (`capture_signals`) is not public, so the uvicorn version is capped in requirements.txt and the stop
    test (`tests/test_runtime.py`) runs the real server."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield

    async def serve(self, sockets=None) -> None:
        try:
            await super().serve(sockets)
        except SystemExit as exc:
            # uvicorn leaves this way when it cannot listen (the port is taken; it has logged why). SystemExit would
            # tear through the event loop, so it becomes an ordinary error: the runtime stops with exit code 1
            raise RuntimeError(f"веб-сервер не запустился (код {exc.code})") from None

    def stop(self) -> None:
        self.should_exit = True


def web_server(
    app: FastAPI, *, host: str, port: int, stop_grace: int, trusted_proxies: Sequence[str] = ()
) -> _Server:
    """The server of `app` on `host:port`. Its records go to the root logger (the process's log, through
    `MaskingFormatter`); the request log is off (`GET /health 200` every 30 seconds says nothing); `stop_grace` is how
    long the started requests get to finish on stop. `trusted_proxies` are the addresses and networks whose
    `X-Forwarded-For` and `X-Forwarded-Proto` are believed (`TRUSTED_PROXIES`, spec 5.2 of stage 7.2); none — the proxy
    headers are ignored altogether (uvicorn would otherwise believe `127.0.0.1` by default)."""
    proxy: dict[str, object] = (
        {"proxy_headers": True, "forwarded_allow_ips": list(trusted_proxies)} if trusted_proxies else {"proxy_headers": False}
    )
    config = uvicorn.Config(
        app, host=host, port=port,
        log_config=None, access_log=False, lifespan="off", ws="none", server_header=False,
        timeout_graceful_shutdown=stop_grace, **proxy,
    )
    return _Server(config)
