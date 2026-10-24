"""Owner allowlist: one gate in front of every incoming Telegram update."""

import logging


class AccessMiddleware:
    """aiogram outer middleware that drops updates from anyone not in the allowlist.

    Fail-closed: an empty allowlist lets nobody in. Strangers get no reply at all.
    """

    def __init__(self, allowed_user_ids) -> None:
        self._allowed = frozenset(allowed_user_ids)

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None or user.id not in self._allowed:
            logging.warning(
                "access denied: user_id=%s update=%s",
                getattr(user, "id", None),
                type(event).__name__,
            )
            return None
        return await handler(event, data)
