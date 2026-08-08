from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

import config
import database
from locales import t

router = Router()


def _puzzles_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("puzzles_button", lang),
                    web_app=WebAppInfo(url=config.MINIAPP_URL),
                )
            ]
        ]
    )


@router.message(Command("puzzles"))
async def cmd_puzzles(message: Message) -> None:
    lang = await database.get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.language_code
    )
    await message.answer(t("puzzles_prompt", lang), reply_markup=_puzzles_keyboard(lang))
