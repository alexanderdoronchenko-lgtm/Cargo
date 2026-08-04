import chess.pgn
from aiogram import F, Router
from aiogram.types import BufferedInputFile, Message

import database
from locales import t
from services.board_image_service import render_position_png
from services.chess_service import (
    GameFetchError,
    count_moves,
    detect_platform,
    extract_url,
    fetch_game_by_url,
    parse_pgn,
)
from services.commentary_service import generate_moment_explanations
from services.engine_service import EngineError, analyze_game, select_top_moments
from services import usage_service

router = Router()

_MAX_CAPTION_LENGTH = 1024


async def _get_lang(message: Message) -> str:
    return await database.get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.language_code
    )


def _truncate_caption(text: str) -> str:
    if len(text) <= _MAX_CAPTION_LENGTH:
        return text
    return text[: _MAX_CAPTION_LENGTH - 1].rstrip() + "…"


async def _send_review(message: Message, lang: str, game: chess.pgn.Game) -> None:
    telegram_id = message.from_user.id
    tier = await database.get_user_tier(telegram_id)
    remaining = await usage_service.get_remaining_analyses(telegram_id, tier)
    if remaining <= 0:
        await message.answer(t("limit_exceeded", lang, limit=usage_service.daily_limit(tier)))
        return

    await message.answer(t("game_received", lang, count=count_moves(game)))
    await message.answer(t("analyzing", lang))

    try:
        critical_moments = await analyze_game(game)
    except EngineError:
        await message.answer(t("engine_error", lang))
        return

    await usage_service.record_analysis(telegram_id)

    if not critical_moments:
        await message.answer(t("no_critical_moments", lang))
        return

    # Logged for /progress (all moments, not just the ones sent to Claude
    # below) so a month's worth of weaknesses can be tracked even for games
    # with more blunders than fit in one review.
    for moment in critical_moments:
        await usage_service.record_critical_moment(
            telegram_id, moment.move_number, moment.move_san, moment.context_san, moment.cp_loss
        )

    critical_moments = select_top_moments(critical_moments)

    explanations, token_usage = await generate_moment_explanations(critical_moments, lang)
    await database.log_token_usage(
        telegram_id, token_usage.input_tokens, token_usage.output_tokens, token_usage.cached_tokens
    )

    for moment, explanation in zip(critical_moments, explanations):
        caption = explanation.strip() or t(
            "moment_fallback_caption",
            lang,
            move_number=moment.move_number,
            move_san=moment.move_san,
            cp_loss=moment.cp_loss,
        )
        photo_bytes = render_position_png(moment.fen_after, moment.move_uci)
        await message.answer_photo(
            BufferedInputFile(photo_bytes, filename="position.png"),
            caption=_truncate_caption(caption),
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

    await _send_review(message, lang, game)


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

        await _send_review(message, lang, game)
        return

    game = parse_pgn(text)
    if game is None:
        await message.answer(t("game_parse_error", lang))
        return

    await _send_review(message, lang, game)
