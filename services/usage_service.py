"""Daily usage limits for game analysis (free / Ruby / Emerald tiers)."""
import database

ACTION_ANALYSIS = "game_analysis"

TIER_FREE = "free"
TIER_RUBY = "ruby"
TIER_EMERALD = "emerald"

# Ruby and Emerald are fair-use ceilings, not real unlimited, until real
# subscription enforcement lands (see the /subscribe step).
DAILY_LIMITS = {
    TIER_FREE: 2,
    TIER_RUBY: 8,
    TIER_EMERALD: 12,
}


def daily_limit(tier: str) -> int:
    return DAILY_LIMITS.get(tier, DAILY_LIMITS[TIER_FREE])


async def get_remaining_analyses(telegram_id: int, tier: str) -> int:
    used = await database.count_usage_last_24h(telegram_id, ACTION_ANALYSIS)
    return max(0, daily_limit(tier) - used)


async def record_analysis(telegram_id: int) -> None:
    await database.log_usage(telegram_id, ACTION_ANALYSIS)
