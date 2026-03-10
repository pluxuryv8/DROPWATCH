from __future__ import annotations

import logging

from dropwatch.common.config import settings
from dropwatch.db import crud
from dropwatch.db.database import get_sessionmaker


logger = logging.getLogger("single_tenant")
OWNER_ONLY_TEXT = "Этот бот привязан к одному владельцу. Доступ разрешен только заказчику."


def single_tenant_enabled() -> bool:
    return settings.owner_tg_id is not None


def is_owner_tg_id(tg_id: int | None) -> bool:
    if settings.owner_tg_id is None:
        return True
    return tg_id == settings.owner_tg_id


async def ensure_owner_user() -> None:
    if settings.owner_tg_id is None:
        logger.warning("OWNER_TG_ID is not set; single-tenant protection is disabled")
        return

    session_maker = get_sessionmaker()
    async with session_maker() as session:
        user = await crud.get_or_create_user(
            session,
            tg_id=settings.owner_tg_id,
            timezone_str=settings.default_timezone,
            default_interval=settings.default_task_interval_sec,
        )
        await crud.get_or_create_settings(
            session,
            user_id=user.id,
            default_interval=user.default_interval_sec,
        )
    logger.info("Owner user ensured: tg_id=%s", settings.owner_tg_id)
