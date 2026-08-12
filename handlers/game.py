import html
import logging
import time

import chess.pgn
from aiogram import F, Router
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

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
from services.commentary_service import generate_review
from services.engine_service import EngineError, TYPE_MISTAKE, analyze_game, select_top_moments
from services import usage_service
from telegram_format import markdown_to_html, truncate_html

router = Router()
logger = logging.getLogger(__name__)

_MAX_CAPTION_LENGTH = 1024

# Keyed by telegram_id, holding the game awaiting a "white or black?" answer
# when the side couldn't be auto-detected from stored usernames. Overwritten
# by any newer game the same user sends before answering — there's only ever
# one live question per user, and an unanswered older one is stale anyway.
# This is the one piece of cross-request state in an otherwise stateless
# codebase (no FSM is used anywhere else), kept deliberately minimal rather
# than pulling in aiogram's FSM machinery for a single yes/no question.
_pending_side_choice: dict[int, chess.pgn.Game] = {}


async def _get_lang(message: Message) -> str:
    return await database.get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.language_code
    )


def _build_side_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("side_button_white", lang), callback_data="side:white"),
                InlineKeyboardButton(text=t("side_button_black", lang), callback_data="side:black"),
            ]
        ]
    )


async def _determine_user_side(telegram_id: int, game: chess.pgn.Game) -> str | None:
    """Matches the PGN's [White]/[Black] tags against the user's stored
    chess.com/lichess usernames (case-insensitively). Returns None — not a
    guess — whenever there's no stored username, neither tag matches, or
    both tags match (e.g. a self-play test game), so the caller can fall
    back to asking explicitly.
    """
    white_tag = (game.headers.get("White") or "").strip().lower()
    black_tag = (game.headers.get("Black") or "").strip().lower()

    chesscom_username, lichess_username = await database.get_chess_usernames(telegram_id)
    candidates = {u.strip().lower() for u in (chesscom_username, lichess_username) if u}
    if not candidates:
        return None

    white_match = bool(white_tag) and white_tag in candidates
    black_match = bool(black_tag) and black_tag in candidates
    if white_match and not black_match:
        return "white"
    if black_match and not white_match:
        return "black"
    return None


async def _send_review(message: Message, lang: str, game: chess.pgn.Game) -> None:
    telegram_id = message.from_user.id
    user_side = await _determine_user_side(telegram_id, game)
    if user_side is None:
        _pending_side_choice[telegram_id] = game
        await message.answer(t("side_question", lang), reply_markup=_build_side_keyboard(lang))
        return

    await _run_review(message, lang, game, user_side)


@router.callback_query(F.data.in_({"side:white", "side:black"}))
async def handle_side_choice(callback: CallbackQuery) -> None:
    telegram_id = callback.from_user.id
    lang = await database.get_or_create_user(
        telegram_id, callback.from_user.username, callback.from_user.language_code
    )
    game = _pending_side_choice.pop(telegram_id, None)
    await callback.message.edit_reply_markup(reply_markup=None)

    if game is None:
        await callback.answer()
        await callback.message.answer(t("side_choice_expired", lang))
        return

    user_side = callback.data.split(":", 1)[1]
    await callback.answer()
    await _run_review(callback.message, lang, game, user_side)


async def _run_review(message: Message, lang: str, game: chess.pgn.Game, user_side: str) -> None:
    telegram_id = message.chat.id

    # Perf instrumentation for the "review takes a minute+" investigation —
    # three buckets asked for (Stockfish, Claude, Telegram sends) plus the
    # overall wall time so any gap not covered by those three (board
    # rendering, DB writes, tier checks) is visible instead of hidden.
    review_started = time.perf_counter()
    telegram_time = 0.0

    async def send(coro):
        nonlocal telegram_time
        started = time.perf_counter()
        try:
            return await coro
        finally:
            telegram_time += time.perf_counter() - started

    if telegram_id != config.ADMIN_USER_ID:
        tier = await database.get_user_tier(telegram_id)
        remaining = await usage_service.get_remaining_analyses(telegram_id, tier)
        if remaining <= 0:
            if tier == usage_service.TIER_FREE:
                await send(message.answer(t("limit_exceeded_free", lang)))
            else:
                await send(message.answer(t("limit_exceeded", lang, limit=usage_service.daily_limit(tier))))
            return

    await send(message.answer(t("game_received", lang, count=count_moves(game))))
    await send(message.answer(t("analyzing", lang)))

    stockfish_started = time.perf_counter()
    try:
        analysis = await analyze_game(game, user_side=user_side)
    except EngineError:
        await send(message.answer(t("engine_error", lang)))
        return
    stockfish_elapsed = time.perf_counter() - stockfish_started

    await usage_service.record_analysis(telegram_id)

    # Only the user's own moves — the whole point of this filter is that the
    # bot must comment on the game from the user's perspective, not the
    # opponent's, and the "ты"-voice prompts in commentary_service assume
    # every moment handed to them belongs to a single player.
    critical_moments = [m for m in analysis.moments if m.side == user_side]
    if not critical_moments:
        await send(message.answer(t("no_critical_moments", lang)))
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

    # Merged into one Claude call (explanations + summary) instead of two
    # sequential ones — see generate_review's docstring for why.
    claude_started = time.perf_counter()
    explanations, summary, token_usage = await generate_review(
        moments_for_captions, critical_moments, analysis.accuracy_pct, lang
    )
    claude_elapsed = time.perf_counter() - claude_started
    await database.log_token_usage(
        telegram_id, token_usage.input_tokens, token_usage.output_tokens, token_usage.cached_tokens
    )

    for moment, explanation in zip(moments_for_captions, explanations):
        if explanation.strip():
            caption = explanation.strip()
        elif moment.type == TYPE_MISTAKE:
            # The mistake fallback still carries real information (the
            # actual cp loss), so it's worth showing even without Claude's
            # commentary. A retry isn't worthwhile here either — temperature
            # is now pinned to 0, so re-sending the identical prompt would
            # very likely reproduce the same empty result.
            caption = t(
                "moment_fallback_caption",
                lang,
                move_number=moment.move_number,
                move_san=moment.move_san,
                cp_loss=moment.cp_loss,
            )
        else:
            # A wordless "strong move" caption carries no real information —
            # skip the card entirely rather than show it. select_top_moments
            # already caps the review at a handful of moments, so silently
            # dropping one under this rare failure mode doesn't leave the
            # review noticeably thinner.
            continue
        photo_bytes = render_position_png(moment.fen_after, moment.move_uci, moment.best_move_uci)
        await send(
            message.answer_photo(
                BufferedInputFile(photo_bytes, filename="position.png"),
                caption=truncate_html(markdown_to_html(caption), _MAX_CAPTION_LENGTH),
            )
        )

    # Grounded in every flagged moment across the whole game, not just the
    # subset that fit in moments_for_captions (generate_review sends both
    # lists), so the summary's per-phase lines reflect the full game the
    # accuracy number was computed from.
    if summary.strip():
        # No formatting is requested from Claude here (plain text), but the
        # message still goes out under parse_mode=HTML — escape defensively
        # so an incidental "<", ">" or "&" in the model's prose can't be
        # misparsed as markup and reject the send.
        await send(message.answer(html.escape(summary)))
    else:
        # Same rationale as the skipped strength captions above: an empty
        # summary carries no information, and Telegram rejects empty
        # message text outright, so skip rather than send a blank message.
        logger.warning(
            "Empty game summary from Claude (telegram_id=%s) — skipping summary message", telegram_id
        )

    total_elapsed = time.perf_counter() - review_started
    logger.info(
        "Review timing telegram_id=%s moments=%d: stockfish=%.2fs "
        "claude=%.2fs (merged explanations+summary, output_tokens=%d "
        "cached_input_tokens=%d/%d) telegram_sends=%.2fs other=%.2fs total=%.2fs",
        telegram_id,
        len(moments_for_captions),
        stockfish_elapsed,
        claude_elapsed,
        token_usage.output_tokens,
        token_usage.cached_tokens,
        token_usage.input_tokens,
        telegram_time,
        total_elapsed - stockfish_elapsed - claude_elapsed - telegram_time,
        total_elapsed,
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

    # Try parsing the message as PGN first — a full PGN can legitimately
    # contain a chess.com/lichess.org URL inside a tag (e.g. [Site] or
    # [Link]), which must not be mistaken for "the user only sent a link".
    # Only fall back to downloading by URL when the text itself isn't a
    # parseable game (a bare link with no moves).
    game = parse_pgn(text)
    if game is not None:
        await _send_review(message, lang, game)
        return

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

    await message.answer(t("game_parse_error", lang))
