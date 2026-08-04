"""Daily usage limits for game analysis (free vs premium tiers)."""
import database

ACTION_ANALYSIS = "game_analysis"

FREE_DAILY_LIMIT = 2
# Premium is fair-use, not truly unlimited, until real subscription
# enforcement lands (see the /subscribe step).
PREMIUM_DAILY_LIMIT = 15


def daily_limit(is_premium: bool) -> int:
    return PREMIUM_DAILY_LIMIT if is_premium else FREE_DAILY_LIMIT


async def get_remaining_analyses(telegram_id: int, is_premium: bool) -> int:
    used = await database.count_usage_last_24h(telegram_id, ACTION_ANALYSIS)
    return max(0, daily_limit(is_premium) - used)


async def record_analysis(telegram_id: int) -> None:
    await database.log_usage(telegram_id, ACTION_ANALYSIS)
