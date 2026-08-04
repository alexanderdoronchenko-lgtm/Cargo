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
}

_TIER_PRICES = {
    "ruby": config.RUBY_PRICE_STARS,
    "emerald": config.EMERALD_PRICE_STARS,
}


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
        ]
    )


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message) -> None:
    lang = await database.get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.language_code
    )
    await message.answer(t("subscribe_prompt", lang), reply_markup=_tier_keyboard(lang))


@router.callback_query(F.data.in_({"subscribe:ruby", "subscribe:emerald"}))
async def cb_subscribe(callback: CallbackQuery) -> None:
    tier = callback.data.split(":", 1)[1]
    lang = await database.get_or_create_user(
        callback.from_user.id, callback.from_user.username, callback.from_user.language_code
    )
    tier_name = t(_TIER_NAME_KEYS[tier], lang)

    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title=t("invoice_title", lang, tier=tier_name),
        description=t(
            "invoice_description",
            lang,
            tier=tier_name,
            days=subscription_service.SUBSCRIPTION_DURATION_DAYS,
        ),
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

    await subscription_service.activate_subscription(message.from_user.id, tier)

    lang = await database.get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.language_code
    )
    tier_name = t(_TIER_NAME_KEYS[tier], lang)
    await message.answer(
        t(
            "subscription_activated",
            lang,
            tier=tier_name,
            days=subscription_service.SUBSCRIPTION_DURATION_DAYS,
        )
    )
