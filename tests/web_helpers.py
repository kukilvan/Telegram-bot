"""What the web tests share."""

from collections.abc import Iterator


def all_routes(app) -> Iterator:
    """Every route of the app that has an address and methods, also those of the included routers (newer FastAPI keeps
    an included router as one entry of `app.routes` and not as its routes)."""
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        inner = getattr(route, "original_router", None)
        if inner is not None:
            stack.extend(inner.routes)
        elif getattr(route, "methods", None):
            yield route
