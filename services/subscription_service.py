"""Telegram Stars subscription lifecycle: activation/upgrade and expiry."""
from datetime import datetime, timedelta, timezone

import config
import database

SUBSCRIPTION_DURATION_DAYS = 30

TIER_PRICES_STARS = {
    "ruby": config.RUBY_PRICE_STARS,
    "emerald": config.EMERALD_PRICE_STARS,
    "diamond": config.DIAMOND_PRICE_STARS,
}

# Ordering for comparing a purchase against an existing subscription.
TIER_ORDER = {"free": 0, "ruby": 1, "emerald": 2, "diamond": 3}


def _new_expiry() -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(days=SUBSCRIPTION_DURATION_DAYS)
    return expires_at.strftime("%Y-%m-%d %H:%M:%S")


async def get_active_subscription(telegram_id: int) -> tuple[str, str] | None:
    """Returns (tier, expires_at) if the user currently has an active paid
    subscription, else None. expires_at is the raw "YYYY-MM-DD HH:MM:SS" UTC
    string stored in the database.
    """
    row = await database.get_active_subscription(telegram_id)
    if row is None:
        return None
    return row["tier"], row["expires_at"]


async def activate_subscription(telegram_id: int, tier: str) -> bool:
    """Activates a new subscription, renews/upgrades an existing one, or —
    when `tier` is lower than an active subscription — queues it as a
    pending downgrade that only takes effect once the current period ends.

    Returns True if the tier was applied immediately, False if it was
    queued instead.
    """
    active = await get_active_subscription(telegram_id)
    if active is not None:
        active_tier, _ = active
        if TIER_ORDER[tier] < TIER_ORDER[active_tier]:
            await database.queue_downgrade(telegram_id, tier)
            return False

    await database.upsert_subscription(telegram_id, tier, _new_expiry())
    await database.set_user_tier(telegram_id, tier)
    return True


async def expire_subscriptions() -> int:
    """Processes every subscription whose period has lapsed: applies a
    queued pending_tier with a fresh period if one was set, otherwise
    downgrades the user back to free. Returns how many users were affected.
    """
    rows = await database.get_lapsed_subscriptions()
    for row in rows:
        telegram_id = row["telegram_id"]
        pending_tier = row["pending_tier"]
        if pending_tier is not None:
            await database.upsert_subscription(telegram_id, pending_tier, _new_expiry())
            await database.set_user_tier(telegram_id, pending_tier)
        else:
            await database.downgrade_to_free(telegram_id)
    return len(rows)
