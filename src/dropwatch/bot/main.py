import asyncio

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from dropwatch.bot.handlers import router
from dropwatch.bot.middleware import OwnerOnlyMiddleware
from dropwatch.common.config import settings
from dropwatch.common.logging import setup_logging
from dropwatch.common.single_tenant import ensure_owner_user, single_tenant_enabled
from dropwatch.db.database import create_db, init_engine


async def _set_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="status", description="Статус сервиса"),
            BotCommand(command="set_proxy", description="Сохранить прокси"),
            BotCommand(command="set_proxy_change_url", description="Сохранить URL смены IP"),
            BotCommand(command="set_link", description="Добавить ссылку поиска"),
            BotCommand(command="set_filters", description="Настроить фильтры"),
            BotCommand(command="start_monitor", description="Включить мониторинг"),
            BotCommand(command="stop_monitor", description="Остановить мониторинг"),
            BotCommand(command="help", description="Как запустить радар"),
        ]
    )


async def main() -> None:
    setup_logging(settings.log_level)
    init_engine(settings.database_url)
    await create_db()
    await ensure_owner_user()

    bot = Bot(token=settings.telegram_token)
    await _set_bot_commands(bot)
    dp = Dispatcher(storage=MemoryStorage())
    if single_tenant_enabled():
        owner_middleware = OwnerOnlyMiddleware()
        dp.message.middleware(owner_middleware)
        dp.callback_query.middleware(owner_middleware)
    dp.include_router(router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
