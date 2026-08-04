from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import database
from locales import t
from services import usage_service

router = Router()


@router.message(Command("balance"))
async def cmd_balance(message: Message) -> None:
    telegram_id = message.from_user.id
    lang = await database.get_or_create_user(
        telegram_id, message.from_user.username, message.from_user.language_code
    )
    is_premium = await database.get_user_premium(telegram_id)
    remaining = await usage_service.get_remaining_analyses(telegram_id, is_premium)
    limit = usage_service.daily_limit(is_premium)

    key = "balance_premium" if is_premium else "balance_free"
    await message.answer(t(key, lang, remaining=remaining, limit=limit))
