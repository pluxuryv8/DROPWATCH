import asyncio

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from dropwatch.bot.handlers import router
from dropwatch.common.config import settings
from dropwatch.common.logging import setup_logging
from dropwatch.db.database import init_db, init_engine


async def main() -> None:
    setup_logging(settings.log_level)
    init_engine(settings.database_url)
    await init_db()

    bot = Bot(token=settings.telegram_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
