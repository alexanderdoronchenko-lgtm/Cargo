"""Telegram Stars subscription lifecycle: activation/upgrade and expiry."""
from datetime import datetime, timedelta, timezone

import config
import database

SUBSCRIPTION_DURATION_DAYS = 30

TIER_PRICES_STARS = {
    "ruby": config.RUBY_PRICE_STARS,
    "emerald": config.EMERALD_PRICE_STARS,
}

# Ordering for comparing a purchase against an existing subscription.
TIER_ORDER = {"free": 0, "ruby": 1, "emerald": 2}


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


async def activate_subscription(telegram_id: int, tier: str) -> None:
    """Activates a new subscription or upgrades an existing one. Always
    replaces the tier and resets expires_at to 30 days from now — never two
    parallel periods, even when upgrading mid-period.
    """
    await database.upsert_subscription(telegram_id, tier, _new_expiry())
    await database.set_user_tier(telegram_id, tier)


async def expire_subscriptions() -> int:
    """Downgrades every user whose subscription has lapsed back to free.
    Returns how many users were downgraded.
    """
    return await database.expire_subscriptions()
