from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

import database
from locales import t

router = Router()


@router.message(Command("chesscom"))
async def cmd_chesscom(message: Message, command: CommandObject) -> None:
    telegram_id = message.from_user.id
    lang = await database.get_or_create_user(
        telegram_id, message.from_user.username, message.from_user.language_code
    )
    username = (command.args or "").strip()

    if not username:
        chesscom_username, _ = await database.get_chess_usernames(telegram_id)
        if chesscom_username:
            await message.answer(t("chesscom_status_set", lang, username=chesscom_username))
        else:
            await message.answer(t("chesscom_status_unset", lang))
        return

    await database.set_chesscom_username(telegram_id, username)
    await message.answer(t("chesscom_saved", lang, username=username))


@router.message(Command("lichess"))
async def cmd_lichess(message: Message, command: CommandObject) -> None:
    telegram_id = message.from_user.id
    lang = await database.get_or_create_user(
        telegram_id, message.from_user.username, message.from_user.language_code
    )
    username = (command.args or "").strip()

    if not username:
        _, lichess_username = await database.get_chess_usernames(telegram_id)
        if lichess_username:
            await message.answer(t("lichess_status_set", lang, username=lichess_username))
        else:
            await message.answer(t("lichess_status_unset", lang))
        return

    await database.set_lichess_username(telegram_id, username)
    await message.answer(t("lichess_saved", lang, username=username))
