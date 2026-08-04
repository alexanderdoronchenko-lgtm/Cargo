from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import database
from locales import t

router = Router()


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    lang = await database.get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.language_code
    )
    await message.answer(t("help_text", lang))
