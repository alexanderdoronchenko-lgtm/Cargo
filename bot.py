"""Entry point: starts the Telegram bot in long-polling mode."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import config
import database
from handlers import main_router
from services.subscription_service import expire_subscriptions

_SUBSCRIPTION_CHECK_INTERVAL_SECONDS = 24 * 60 * 60


async def _subscription_expiry_loop() -> None:
    while True:
        try:
            downgraded = await expire_subscriptions()
            if downgraded:
                logging.info("Downgraded %d expired subscription(s) to free", downgraded)
        except Exception:
            logging.exception("Subscription expiry check failed")
        await asyncio.sleep(_SUBSCRIPTION_CHECK_INTERVAL_SECONDS)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    await database.init_db()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(main_router)

    asyncio.create_task(_subscription_expiry_loop())

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
