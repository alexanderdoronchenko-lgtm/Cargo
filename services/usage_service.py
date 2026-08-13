"""Usage limits for game analysis: a rolling weekly allowance for the free
tier, and daily fair-use ceilings for paid tiers.
"""
import database

ACTION_ANALYSIS = "game_analysis"
ACTION_CRITICAL_MOMENT = "critical_moment"

TIER_FREE = "free"
TIER_RUBY = "ruby"
TIER_EMERALD = "emerald"
TIER_DIAMOND = "diamond"

# The free tier gets 2 analyses per rolling 7-day window (database.
# count_usage_last_7d) — a periodic allowance, not a one-time trial: it
# refreshes as old usage rows age out of the window, rather than staying
# exhausted forever after the first couple of analyses.
FREE_WEEKLY_LIMIT = 2

# Ruby, Emerald, and Diamond are fair-use ceilings, not real unlimited, until
# real subscription enforcement lands (see the /subscribe step). Unlike the
# free tier, these refresh daily (database.count_usage_last_24h).
DAILY_LIMITS = {
    TIER_RUBY: 10,
    TIER_EMERALD: 15,
    TIER_DIAMOND: 20,
}


def daily_limit(tier: str) -> int:
    """The per-day limit for a paid tier. Not meaningful for the free tier
    — see FREE_WEEKLY_LIMIT instead.
    """
    return DAILY_LIMITS.get(tier, DAILY_LIMITS[TIER_RUBY])


async def get_remaining_analyses(telegram_id: int, tier: str) -> int:
    if tier == TIER_FREE:
        used = await database.count_usage_last_7d(telegram_id, ACTION_ANALYSIS)
        return max(0, FREE_WEEKLY_LIMIT - used)
    used = await database.count_usage_last_24h(telegram_id, ACTION_ANALYSIS)
    return max(0, daily_limit(tier) - used)


async def record_analysis(telegram_id: int) -> None:
    await database.log_usage(telegram_id, ACTION_ANALYSIS)


async def record_critical_moment(
    telegram_id: int, move_number: int, move_san: str, context_san: str, cp_loss: int
) -> None:
    await database.log_usage(
        telegram_id,
        ACTION_CRITICAL_MOMENT,
        move_number=move_number,
        move_san=move_san,
        context_san=context_san,
        cp_loss=cp_loss,
    )
