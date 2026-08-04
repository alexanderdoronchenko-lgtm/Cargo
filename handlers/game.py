from aiogram import F, Router
from aiogram.types import Message

import database
from locales import t
from services.chess_service import (
    GameFetchError,
    count_moves,
    detect_platform,
    extract_url,
    fetch_game_by_url,
    parse_pgn,
)

router = Router()


async def _get_lang(message: Message) -> str:
    return await database.get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.language_code
    )


@router.message(F.document)
async def handle_pgn_file(message: Message) -> None:
    lang = await _get_lang(message)
    file_name = message.document.file_name or ""
    if not file_name.lower().endswith(".pgn"):
        await message.answer(t("game_parse_error", lang))
        return

    buffer = await message.bot.download(message.document)
    text = buffer.read().decode("utf-8", errors="ignore")

    game = parse_pgn(text)
    if game is None:
        await message.answer(t("game_parse_error", lang))
        return

    await message.answer(t("game_received", lang, count=count_moves(game)))


@router.message(F.text)
async def handle_pgn_text(message: Message) -> None:
    lang = await _get_lang(message)
    text = message.text

    url = extract_url(text)
    if url:
        platform = detect_platform(url)
        if platform is None:
            await message.answer(t("link_unsupported", lang))
            return

        try:
            pgn_text = await fetch_game_by_url(url, platform)
        except GameFetchError as exc:
            await message.answer(t(f"game_fetch_error_{exc.reason}", lang))
            return

        game = parse_pgn(pgn_text)
        if game is None:
            await message.answer(t("game_parse_error", lang))
            return

        await message.answer(t("game_received", lang, count=count_moves(game)))
        return

    game = parse_pgn(text)
    if game is None:
        await message.answer(t("game_parse_error", lang))
        return

    await message.answer(t("game_received", lang, count=count_moves(game)))
