import html
import logging
import time

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import config
import database
from locales import t
from services import progress_service, usage_service
from services.commentary_service import model_for_tier

router = Router()
logger = logging.getLogger(__name__)

_PROGRESS_WINDOW_DAYS = 30


@router.message(Command("progress"))
async def cmd_progress(message: Message) -> None:
    telegram_id = message.from_user.id
    lang = await database.get_or_create_user(
        telegram_id, message.from_user.username, message.from_user.language_code
    )

    # Fetched unconditionally (not just for the limit check below) since it
    # also picks the summary's provider — an admin account still gets its
    # own real tier's provider, just without the usage-limit gate. Mirrors
    # handlers/game.py's _run_review.
    tier = await database.get_user_tier(telegram_id)

    if telegram_id != config.ADMIN_USER_ID:
        remaining = await usage_service.get_remaining_progress_summaries(telegram_id)
        if remaining <= 0:
            await message.answer(
                t("progress_limit_exceeded", lang, limit=usage_service.PROGRESS_DAILY_LIMIT)
            )
            return

    moments = await database.get_critical_moments_since(
        telegram_id, usage_service.ACTION_CRITICAL_MOMENT, _PROGRESS_WINDOW_DAYS
    )
    if not moments:
        await message.answer(t("progress_no_data", lang))
        return

    await message.answer(t("progress_analyzing", lang))

    # Counted against the daily limit here, right before the LLM call it
    # gates — same timing as handlers/game.py's record_analysis relative to
    # generate_review: one use is spent on the attempt itself, regardless
    # of whether the resulting summary text ends up empty.
    await usage_service.record_progress_summary(telegram_id)

    started = time.perf_counter()
    summary, token_usage = await progress_service.summarize_weaknesses(moments, lang, tier)
    elapsed = time.perf_counter() - started
    model = model_for_tier(tier)

    await database.log_token_usage(
        telegram_id, token_usage.input_tokens, token_usage.output_tokens, token_usage.cached_tokens
    )
    logger.info(
        "Progress timing telegram_id=%s tier=%s model=%s moments=%d: elapsed=%.2fs "
        "(output_tokens=%d non_cached_input_tokens=%d cached_input_tokens=%d)",
        telegram_id,
        tier,
        model,
        len(moments),
        elapsed,
        token_usage.output_tokens,
        token_usage.input_tokens,
        token_usage.cached_tokens,
    )

    if not summary.strip():
        # Same empty-response guard as the game-review summary in
        # handlers/game.py — without it, a blank `summary` here used to
        # produce a message that was just progress_header with nothing
        # after it, which read as the command silently failing rather
        # than as an actual error.
        logger.warning("Empty /progress summary from %s (telegram_id=%s)", model, telegram_id)
        await message.answer(t("progress_generation_error", lang))
        return

    # No formatting is requested from the model here (plain text), but the
    # message still goes out under parse_mode=HTML — escape defensively so
    # an incidental "<", ">" or "&" in its prose can't be misparsed as
    # markup and reject the send.
    await message.answer(f"{t('progress_header', lang)}\n\n{html.escape(summary)}")
