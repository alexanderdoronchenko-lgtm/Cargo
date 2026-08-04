from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import database
from locales import t

router = Router()

_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Русский", callback_data="lang:ru"),
            InlineKeyboardButton(text="English", callback_data="lang:en"),
        ]
    ]
)


@router.message(Command("language"))
async def cmd_language(message: Message) -> None:
    lang = await database.get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.language_code
    )
    await message.answer(t("language_prompt", lang), reply_markup=_KEYBOARD)


@router.callback_query(F.data.in_({"lang:ru", "lang:en"}))
async def cb_set_language(callback: CallbackQuery) -> None:
    lang = callback.data.split(":", 1)[1]
    await database.set_user_language(callback.from_user.id, lang)
    await callback.message.edit_text(t("language_changed", lang))
    await callback.answer()
