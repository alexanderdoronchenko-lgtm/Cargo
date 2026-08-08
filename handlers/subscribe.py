from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

import config
import database
from locales import t
from services import subscription_service

router = Router()

_TIER_NAME_KEYS = {
    "ruby": "tier_ruby",
    "emerald": "tier_emerald",
    "diamond": "tier_diamond",
}

_TIER_PRICES = {
    "ruby": config.RUBY_PRICE_STARS,
    "emerald": config.EMERALD_PRICE_STARS,
    "diamond": config.DIAMOND_PRICE_STARS,
}


def _tier_name(tier: str, lang: str) -> str:
    return t(_TIER_NAME_KEYS[tier], lang)


def _format_date(expires_at: str) -> str:
    return expires_at.split(" ")[0]


def _tier_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("subscribe_button_ruby", lang, price=config.RUBY_PRICE_STARS),
                    callback_data="subscribe:ruby",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("subscribe_button_emerald", lang, price=config.EMERALD_PRICE_STARS),
                    callback_data="subscribe:emerald",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("subscribe_button_diamond", lang, price=config.DIAMOND_PRICE_STARS),
                    callback_data="subscribe:diamond",
                )
            ],
        ]
    )


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message) -> None:
    telegram_id = message.from_user.id
    lang = await database.get_or_create_user(
        telegram_id, message.from_user.username, message.from_user.language_code
    )

    active = await subscription_service.get_active_subscription(telegram_id)
    if active is not None:
        active_tier, expires_at = active
        prompt = t(
            "subscribe_prompt_active",
            lang,
            tier=_tier_name(active_tier, lang),
            expires_at=_format_date(expires_at),
        )
    else:
        prompt = t("subscribe_prompt", lang)

    await message.answer(prompt, reply_markup=_tier_keyboard(lang))


@router.callback_query(F.data.in_({"subscribe:ruby", "subscribe:emerald", "subscribe:diamond"}))
async def cb_subscribe(callback: CallbackQuery) -> None:
    tier = callback.data.split(":", 1)[1]
    telegram_id = callback.from_user.id
    lang = await database.get_or_create_user(
        telegram_id, callback.from_user.username, callback.from_user.language_code
    )
    tier_name = _tier_name(tier, lang)

    # Check for an existing subscription before purchase — a live check
    # (not the daily-synced users.subscription_tier) so it's accurate right
    # up to the moment of payment.
    active = await subscription_service.get_active_subscription(telegram_id)

    if active is not None:
        active_tier, expires_at = active

        if subscription_service.TIER_ORDER[tier] < subscription_service.TIER_ORDER[active_tier]:
            # Buying a lower tier than what's active doesn't replace it —
            # the current tier stays active until it expires, and the new
            # (lower) tier takes over only then. Still send the invoice, but
            # with wording that explains the deferred activation.
            description = t(
                "invoice_description_downgrade",
                lang,
                tier=tier_name,
                current_tier=_tier_name(active_tier, lang),
                expires_at=_format_date(expires_at),
            )
        elif tier == active_tier:
            description = t(
                "invoice_description_renew",
                lang,
                tier=tier_name,
                expires_at=_format_date(expires_at),
                days=subscription_service.SUBSCRIPTION_DURATION_DAYS,
            )
        else:
            description = t(
                "invoice_description_upgrade",
                lang,
                tier=tier_name,
                current_tier=_tier_name(active_tier, lang),
                days=subscription_service.SUBSCRIPTION_DURATION_DAYS,
            )
    else:
        description = t(
            "invoice_description",
            lang,
            tier=tier_name,
            days=subscription_service.SUBSCRIPTION_DURATION_DAYS,
        )

    await callback.bot.send_invoice(
        chat_id=telegram_id,
        title=t("invoice_title", lang, tier=tier_name),
        description=description,
        payload=f"subscription:{tier}",
        currency="XTR",
        prices=[LabeledPrice(label=tier_name, amount=_TIER_PRICES[tier])],
    )
    await callback.answer()


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message) -> None:
    payment = message.successful_payment
    tier = payment.invoice_payload.split(":", 1)[1]

    applied = await subscription_service.activate_subscription(message.from_user.id, tier)

    lang = await database.get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.language_code
    )
    tier_name = _tier_name(tier, lang)
    if applied:
        await message.answer(
            t(
                "subscription_activated",
                lang,
                tier=tier_name,
                days=subscription_service.SUBSCRIPTION_DURATION_DAYS,
            )
        )
    else:
        await message.answer(t("subscription_queued", lang, tier=tier_name))
