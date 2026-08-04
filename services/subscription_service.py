"""Telegram Stars subscription lifecycle: activation/upgrade and expiry."""
from datetime import datetime, timedelta, timezone

import config
import database

SUBSCRIPTION_DURATION_DAYS = 30

TIER_PRICES_STARS = {
    "ruby": config.RUBY_PRICE_STARS,
    "emerald": config.EMERALD_PRICE_STARS,
}


def _new_expiry() -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(days=SUBSCRIPTION_DURATION_DAYS)
    return expires_at.strftime("%Y-%m-%d %H:%M:%S")


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
