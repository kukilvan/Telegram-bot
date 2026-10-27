"""The FastAPI app. For now only `/health`; the login and the pages come next."""

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse


def create_web_app(*, health: Callable[[], tuple[int, dict[str, object]]]) -> FastAPI:
    """The web app. `health` is the process's own report (`Health.report`): it reads neither the database nor the
    network, so `/health` answers even when they are slow."""
    # No /docs, /redoc or /openapi.json: they would describe every address to anyone who asks
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health_check() -> JSONResponse:
        status, body = health()
        return JSONResponse(body, status_code=status)

    return app
