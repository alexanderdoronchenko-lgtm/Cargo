import html

import chess.pgn
from aiogram import F, Router
from aiogram.types import BufferedInputFile, Message

import config
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
from services.commentary_service import generate_game_summary, generate_moment_explanations
from services.engine_service import EngineError, TYPE_MISTAKE, analyze_game, select_top_moments
from services import usage_service
from telegram_format import markdown_to_html, truncate_html

router = Router()

_MAX_CAPTION_LENGTH = 1024


async def _get_lang(message: Message) -> str:
    return await database.get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.language_code
    )


async def _send_review(message: Message, lang: str, game: chess.pgn.Game) -> None:
    telegram_id = message.from_user.id
    if telegram_id != config.ADMIN_USER_ID:
        tier = await database.get_user_tier(telegram_id)
        remaining = await usage_service.get_remaining_analyses(telegram_id, tier)
        if remaining <= 0:
            if tier == usage_service.TIER_FREE:
                await message.answer(t("limit_exceeded_free", lang))
            else:
                await message.answer(t("limit_exceeded", lang, limit=usage_service.daily_limit(tier)))
            return

    await message.answer(t("game_received", lang, count=count_moves(game)))
    await message.answer(t("analyzing", lang))

    try:
        analysis = await analyze_game(game)
    except EngineError:
        await message.answer(t("engine_error", lang))
        return

    await usage_service.record_analysis(telegram_id)

    critical_moments = analysis.moments
    if not critical_moments:
        await message.answer(t("no_critical_moments", lang))
        return

    # Logged for /progress and targeted puzzle selection (all mistakes, not
    # just the ones sent to Claude below) so a month's worth of weaknesses
    # can be tracked even for games with more blunders than fit in one
    # review. Strength moments are deliberately excluded here — that
    # tracking is weakness-only, and a good move logged alongside real
    # mistakes would skew both features toward a false "weakness".
    for moment in critical_moments:
        if moment.type != TYPE_MISTAKE:
            continue
        await usage_service.record_critical_moment(
            telegram_id, moment.move_number, moment.move_san, moment.context_san, moment.cp_loss
        )

    moments_for_captions = select_top_moments(critical_moments)

    explanations, token_usage = await generate_moment_explanations(moments_for_captions, lang)
    await database.log_token_usage(
        telegram_id, token_usage.input_tokens, token_usage.output_tokens, token_usage.cached_tokens
    )

    for moment, explanation in zip(moments_for_captions, explanations):
        if explanation.strip():
            caption = explanation.strip()
        elif moment.type == TYPE_MISTAKE:
            caption = t(
                "moment_fallback_caption",
                lang,
                move_number=moment.move_number,
                move_san=moment.move_san,
                cp_loss=moment.cp_loss,
            )
        else:
            caption = t(
                "moment_fallback_caption_strength",
                lang,
                move_number=moment.move_number,
                move_san=moment.move_san,
            )
        photo_bytes = render_position_png(moment.fen_after, moment.move_uci, moment.best_move_uci)
        await message.answer_photo(
            BufferedInputFile(photo_bytes, filename="position.png"),
            caption=truncate_html(markdown_to_html(caption), _MAX_CAPTION_LENGTH),
        )

    # Grounded in every flagged moment across the whole game, not just the
    # subset that fit in moments_for_captions, so the summary's per-phase
    # lines reflect the full game the accuracy number was computed from.
    summary, summary_usage = await generate_game_summary(critical_moments, analysis.accuracy_pct, lang)
    await database.log_token_usage(
        telegram_id, summary_usage.input_tokens, summary_usage.output_tokens, summary_usage.cached_tokens
    )
    # No formatting is requested from Claude here (plain text), but the
    # message still goes out under parse_mode=HTML — escape defensively so
    # an incidental "<", ">" or "&" in the model's prose can't be misparsed
    # as markup and reject the send.
    await message.answer(html.escape(summary))


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
