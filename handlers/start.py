from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

import database

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await database.upsert_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "Привет! Я бот-аналитик на базе Claude.\n"
        "Просто отправь мне текст, и я его проанализирую."
    )
