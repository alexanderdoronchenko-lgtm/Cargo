from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import config
import database
from locales import t
from services import usage_service

router = Router()

_TIER_NAME_KEYS = {
    usage_service.TIER_FREE: "tier_free",
    usage_service.TIER_RUBY: "tier_ruby",
    usage_service.TIER_EMERALD: "tier_emerald",
    usage_service.TIER_DIAMOND: "tier_diamond",
}


@router.message(Command("balance"))
async def cmd_balance(message: Message) -> None:
    telegram_id = message.from_user.id
    lang = await database.get_or_create_user(
        telegram_id, message.from_user.username, message.from_user.language_code
    )
    if telegram_id == config.ADMIN_USER_ID:
        await message.answer(t("balance_admin", lang))
        return

    tier = await database.get_user_tier(telegram_id)
    remaining = await usage_service.get_remaining_analyses(telegram_id, tier)
    tier_name = t(_TIER_NAME_KEYS.get(tier, "tier_free"), lang)

    if tier == usage_service.TIER_FREE:
        await message.answer(
            t(
                "balance_status_free",
                lang,
                remaining=remaining,
                limit=usage_service.FREE_WEEKLY_LIMIT,
                tier=tier_name,
            )
        )
        return

    limit = usage_service.daily_limit(tier)
    await message.answer(
        t("balance_status", lang, remaining=remaining, limit=limit, tier=tier_name)
    )
