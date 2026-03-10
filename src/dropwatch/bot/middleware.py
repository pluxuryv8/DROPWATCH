from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from dropwatch.common.single_tenant import OWNER_ONLY_TEXT, is_owner_tg_id, single_tenant_enabled


logger = logging.getLogger("bot.access")


class OwnerOnlyMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not single_tenant_enabled():
            return await handler(event, data)

        from_user = getattr(event, "from_user", None)
        if is_owner_tg_id(getattr(from_user, "id", None)):
            return await handler(event, data)

        logger.warning("Unauthorized Telegram access denied: user_id=%s", getattr(from_user, "id", None))
        if isinstance(event, Message):
            await event.answer(OWNER_ONLY_TEXT)
            return None
        if isinstance(event, CallbackQuery):
            await event.answer(OWNER_ONLY_TEXT, show_alert=True)
            return None
        return None
