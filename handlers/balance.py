from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import database
from locales import t
from services import usage_service

router = Router()

_TIER_NAME_KEYS = {
    usage_service.TIER_FREE: "tier_free",
    usage_service.TIER_RUBY: "tier_ruby",
    usage_service.TIER_EMERALD: "tier_emerald",
}


@router.message(Command("balance"))
async def cmd_balance(message: Message) -> None:
    telegram_id = message.from_user.id
    lang = await database.get_or_create_user(
        telegram_id, message.from_user.username, message.from_user.language_code
    )
    tier = await database.get_user_tier(telegram_id)
    remaining = await usage_service.get_remaining_analyses(telegram_id, tier)
    limit = usage_service.daily_limit(tier)
    tier_name = t(_TIER_NAME_KEYS.get(tier, "tier_free"), lang)

    await message.answer(
        t("balance_status", lang, remaining=remaining, limit=limit, tier=tier_name)
    )
