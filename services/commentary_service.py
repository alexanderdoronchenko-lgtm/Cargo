"""Turns a game's critical moments into per-moment Telegram-ready explanations,
written in the style captured by chess_style_corpus.md.

Model is chosen by subscription tier: Diamond uses Claude
(claude-sonnet-5), fired as N concurrent per-moment calls (see
_generate_review_claude). Free/Ruby/Emerald use Gemini (config.GEMINI_MODEL,
default gemini-3-flash-preview), fired as several small parallel batches of 2-3
moments each plus a separate summary call (see _generate_review_gemini) —
a failed batch only loses its own couple of moments' explanations instead
of the whole review's commentary. All Gemini calls across the whole
process share a global concurrency semaphore and a requests-per-minute
limiter (see _gemini_semaphore/_gemini_rate_limiter below), since a review
now fires several concurrent Gemini calls instead of one and the free-tier
API key has a real per-minute quota to protect.
"""
import asyncio
import collections
import contextlib
import functools
import json
import logging
import math
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from google.genai import types as genai_types

import config
from services.claude_service import client
from services.engine_service import TYPE_STRENGTH, CriticalMoment
from services.gemini_service import client as gemini_client

logger = logging.getLogger(__name__)

_CORPUS_PATH = config.BASE_DIR / "chess_style_corpus.md"

_LANGUAGE_NAMES = {"ru": "русском", "en": "английском"}

_ROLE_PROMPT = (
    "Ты — шахматный тренер, гроссмейстер. Ты разбираешь партии своих учеников "
    "после игры и живо, по-человечески комментируешь ключевые моменты: где ход был "
    "точным и сильным, где — зевком, где — стратегической неточностью. Твоя речь — "
    "это разбор коуча, а не сухой отчёт движка."
)

_STYLE_INSTRUCTIONS = (
    "Ниже — корпус примеров твоих прошлых разборов партий. Обрати внимание на "
    "плотность и структуру этих разборов: комментарии начинаются примерно с того "
    "момента, где партия отходит от книжной теории (а не с первого хода дебюта), а "
    "дальше по ходу всей партии естественно отмечаются значимые моменты — не только "
    "ошибки и зевки, но и точные, сильные ходы. Это не жёсткое деление на «весь "
    "дебют построчно» и «отдельный список критических моментов» — плотность "
    "комментариев естественная, обычно 6-12 на партию, без формальных разделов. В "
    "конце разбора — короткая сводка: точность с оценочной фразой, и по строке на "
    "дебют, тактику/стратегию и эндшпиль. "
    "Используй эти примеры как ПРИМЕРЫ ТОНА И МАНЕРЫ: как ты формулируешь мысли, "
    "длину фраз, обороты речи, баланс похвалы и критики, стиль итоговой оценки. Это "
    "НЕ образец языка ответа — корпус написан по-русски, но отвечать ты будешь на "
    "языке, указанном в запросе пользователя, даже если он отличается от языка "
    "примеров. Копируй манеру объяснения, а не язык."
)


@functools.lru_cache(maxsize=1)
def _load_style_corpus() -> str:
    return _CORPUS_PATH.read_text(encoding="utf-8")


def build_system_prompt() -> list[dict]:
    return [
        {"type": "text", "text": _ROLE_PROMPT},
        {"type": "text", "text": _STYLE_INSTRUCTIONS},
        {
            "type": "text",
            "text": _load_style_corpus(),
            # Requests are infrequent across a day, so the default 5-minute
            # TTL would constantly expire between different users' games.
            # 1h keeps it warm across the day's traffic (write costs 2x
            # instead of 1.25x, but pays off after ~3 reads within the hour).
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        },
    ]


def _explanation_task_instructions(lang_name: str) -> str:
    # Fixed across every per-moment call within a review (only the moment
    # data in the user message varies) — lives in the *system* prompt
    # precisely so it's cached once and read N times, not resent in full on
    # every one of the N concurrent calls. Moving this ~800-token block out
    # of `messages` was the actual fix for the non-cached-token blowup:
    # duplicated across 10-13 calls, it was ~9000 of the ~9239 tokens
    # originally measured — far more than any cache-write race ever cost.
    return (
        "Для КАЖДОГО момента, описанного в пользовательском сообщении, "
        "напиши отдельное объяснение в своей манере — живой комментарий "
        "тренера, а не механический вердикт «ошибка/не ошибка», и НИКОГДА не "
        "оставляй объяснение пустым — оно должно быть содержательным, без "
        "исключений. "
        "Для ОШИБКИ: как и в примерах выше, можно сначала коротко отметить, что "
        "было хорошо в позиции или замысле перед сбоем, прежде чем объяснить сам "
        "промах — но объяснение должно оставаться правдивым: перед тобой реальная "
        "ошибка, не выдумывай похвалу самому ходу. "
        "Для СИЛЬНОГО ХОДА пиши по той же конкретной схеме, что и для ошибки: "
        "сначала — что именно даёт этот ход (материал, позиционный перевес, атаку "
        "на короля, инициативу), затем — почему это было не очевидно или сложно "
        "найти (например, единственный ход, спасающий партию, тихий манёвр без "
        "размена, который легко пропустить, или точный расчёт варианта). Не "
        "ограничивайся общими словами вроде «отличный ход» — назови конкретный "
        "эффект хода, так же предметно, как объясняешь ошибки. Это будет подпись "
        "под картинкой позиции в Telegram, поэтому объяснение должно быть "
        "коротким — 1-3 предложения по существу, без вступлений. "
        f"Пиши на языке: {lang_name}, сохраняя тот же стиль и манеру объяснения, что "
        "в примерах выше, даже если примеры на другом языке. Для форматирования "
        "используй **двойные звёздочки** для акцентов и `одинарные обратные кавычки` "
        "для нотации ходов (например, `Qxf6`) — это конвертируется в HTML на нашей "
        "стороне. Не используй заголовки, таблицы или другую разметку. Верни ТОЛЬКО "
        "само объяснение — без вступлений, без повторения хода, без кавычек вокруг "
        "текста."
    )


def build_explanation_system_prompt(language: str) -> list[dict]:
    """Same role/style/corpus as build_system_prompt, plus the fixed
    per-moment task instructions — cache_control moves to this last block,
    which caches the whole prefix (role+style+corpus+instructions) as one
    unit. Language-specific (two cache entries, "ru" and "en"), which is
    fine: every call within one review shares the same language, so all N
    concurrent explanation calls in a review still hit the same entry.
    """
    lang_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["en"])
    return [
        {"type": "text", "text": _ROLE_PROMPT},
        {"type": "text", "text": _STYLE_INSTRUCTIONS},
        {"type": "text", "text": _load_style_corpus()},
        {
            "type": "text",
            "text": _explanation_task_instructions(lang_name),
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        },
    ]


def _format_moments(moments: list[CriticalMoment]) -> str:
    if not moments:
        return "Отмеченных моментов в партии не найдено."

    lines = []
    for m in moments:
        side = "белые" if m.side == "white" else "чёрные"
        if m.type == TYPE_STRENGTH:
            lines.append(
                f"- Ход {m.move_number} ({side}), СИЛЬНЫЙ ХОД: контекст `{m.context_san}`; "
                f"сыгранный ход — `{m.move_san}` (совпадает с лучшим ходом движка). "
                f"Оценка до хода: {m.score_before_cp:+d} сп, после: {m.score_after_cp:+d} сп."
            )
        else:
            lines.append(
                f"- Ход {m.move_number} ({side}), ОШИБКА: контекст `{m.context_san}`; "
                f"критический ход — `{m.move_san}`, лучший ход по движку — "
                f"`{m.best_move_san}`. Оценка до хода: {m.score_before_cp:+d} сп, "
                f"после: {m.score_after_cp:+d} сп (потеря {m.cp_loss} сп)."
            )
    return "\n".join(lines)


def _summary_prompt(all_moments: list[CriticalMoment], accuracy_pct: float, language: str) -> str:
    # Shared by both providers' summary call (_generate_game_summary for
    # Claude, _generate_game_summary_gemini for Gemini) — the closing
    # summary's shape doesn't depend on which model writes it.
    lang_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["en"])

    return (
        f"Точность партии по движку: {accuracy_pct:.1f}%.\n\n"
        "Отмеченные моменты партии для контекста (они уже прокомментированы "
        f"отдельно, не нужно пересказывать каждый):\n\n{_format_moments(all_moments)}\n\n"
        "Напиши ТОЛЬКО короткую итоговую сводку партии — тот блок, которым "
        "заканчивается каждый разбор в примерах выше (после «По общей оценке "
        "у тебя:»), и ничего больше: без вступления, без пересказа отдельных "
        "ходов, без заключения после сводки. Сначала оценочная фраза вместе "
        f"с процентом точности ({accuracy_pct:.1f}%), затем по одной короткой "
        "строке (одно-два предложения, не абзац) на дебют, на тактику/"
        "стратегию и на эндшпиль, опираясь на то, что реально было в партии "
        "(моменты выше и то, в какой стадии партии они случились). В "
        "примерах выше эта сводка целиком — 3-5 коротких строк, ориентируйся "
        "на тот же объём. Обычный текст, без разметки и без списков, в своей "
        f"обычной манере. Пиши на языке: {lang_name}, сохраняя тот же стиль и "
        "манеру, что в примерах выше, даже если примеры на другом языке."
    )


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int
    cached_tokens: int

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cached_tokens + other.cached_tokens,
        )


# A single explanation's real content tops out around 160 characters in the
# corpus (~73 tokens at ~2.2 chars/token for Cyrillic) — no JSON envelope
# overhead now that each call returns one plain-text explanation instead of
# a shared array, so the margin above that is pure generation headroom.
_EXPLANATION_MAX_TOKENS = 250

# The corpus's own closing blocks are short — measured at 145-180 characters
# total across all 8 examples (one evaluative phrase + 3-4 one-line notes).
_SUMMARY_MAX_TOKENS = 700


async def _warm_prompt_cache(language: str, semaphore: asyncio.Semaphore) -> TokenUsage:
    """Writes the explanation system prompt's cache entry with a single
    throwaway call *before* the real fan-out in generate_review, so every
    one of the N concurrent explanation calls below reads an already-warm
    cache instead of racing to write it themselves.

    A cache entry only becomes readable once some request has finished
    writing it — firing N calls with an identical system prompt at the same
    instant (as generate_review's asyncio.gather does) means several of
    them could start before any entry exists, each paying full
    (cache-creation) price for the ~4600-token role+style+corpus+
    instructions block independently. This guarantees exactly one write
    instead of a possible 2-3.

    Note this is a secondary saving next to the real fix: the dominant cost
    (measured at ~9000 of ~9239 non-cached tokens in production) was the
    ~800-token task-instructions block being resent in full on every one of
    the N *messages* (never cacheable there, regardless of this function) —
    now moved into build_explanation_system_prompt's cached system prompt
    instead. This warm-up only helps with the much smaller remaining
    cache-write race on that system prompt itself.

    max_tokens=0 returns as soon as the cache write completes with zero
    output tokens billed — cheaper and faster than waiting on a real call
    to prime the cache incidentally.
    """
    try:
        async with semaphore:
            response = await client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=0,
                thinking={"type": "disabled"},
                system=build_explanation_system_prompt(language),
                messages=[{"role": "user", "content": "warmup"}],
            )
    except Exception:
        # Best-effort only — if this fails, the real calls below just fall
        # back to today's behavior (each may or may not hit a warm cache),
        # not a failed review.
        return TokenUsage(0, 0, 0)

    return TokenUsage(
        input_tokens=response.usage.input_tokens + response.usage.cache_creation_input_tokens,
        output_tokens=response.usage.output_tokens,
        cached_tokens=response.usage.cache_read_input_tokens,
    )


async def _generate_moment_explanation(
    moment: CriticalMoment, language: str, semaphore: asyncio.Semaphore
) -> tuple[str, TokenUsage]:
    """One Claude call per moment instead of a shared batch call — run
    concurrently (see generate_review) so wall time tracks the slowest
    individual call instead of the sum of all of them, at the cost of
    firing more requests (bounded by `semaphore` against Anthropic rate
    limits).

    The user message below carries only this one moment's data — the task
    instructions (formatting rules, mistake/strength templates, language)
    live in build_explanation_system_prompt's *system* prompt instead, so
    they're cached once per review and read by every other call in the
    same batch, rather than resent in full N times.
    """
    user_prompt = (
        "Вот отмеченный момент партии — указан его тип: ОШИБКА (потеря в "
        "оценке по движку больше 100 сантипешек) или СИЛЬНЫЙ ХОД (совпадение "
        "с лучшим ходом движка в непростой позиции, либо заметный прирост "
        f"оценки без простого взятия материала):\n\n{_format_moments([moment])}\n\n"
        "Напиши объяснение для этого момента по инструкциям из системного "
        "промпта."
    )

    async with semaphore:
        response = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=_EXPLANATION_MAX_TOKENS,
            # Formulaic style-mimicry, not a reasoning task — disabling
            # thinking keeps the tight budget entirely for visible output.
            thinking={"type": "disabled"},
            # No sampling controls on this model: claude-sonnet-5 rejects
            # temperature/top_p/top_k entirely (400 invalid_request_error) —
            # there is no server-side knob for determinism here. The
            # empty-explanation bug this used to guard against is instead
            # addressed by the "never leave explanation empty" directive and
            # the concrete mistake/strength instructions in the system
            # prompt above.
            system=build_explanation_system_prompt(language),
            messages=[{"role": "user", "content": user_prompt}],
        )

    explanation = "".join(block.text for block in response.content if block.type == "text").strip()
    usage = TokenUsage(
        input_tokens=response.usage.input_tokens + response.usage.cache_creation_input_tokens,
        output_tokens=response.usage.output_tokens,
        cached_tokens=response.usage.cache_read_input_tokens,
    )
    return explanation, usage


async def _generate_game_summary(
    all_moments: list[CriticalMoment], accuracy_pct: float, language: str, semaphore: asyncio.Semaphore
) -> tuple[str, TokenUsage]:
    """Returns the short end-of-game summary described by the corpus — an
    evaluative phrase with the accuracy percentage, plus one line each on
    the opening, tactics/strategy, and the endgame.
    """
    async with semaphore:
        response = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=_SUMMARY_MAX_TOKENS,
            thinking={"type": "disabled"},
            system=build_system_prompt(),
            messages=[{"role": "user", "content": _summary_prompt(all_moments, accuracy_pct, language)}],
        )

    summary = "".join(block.text for block in response.content if block.type == "text").strip()
    usage = TokenUsage(
        input_tokens=response.usage.input_tokens + response.usage.cache_creation_input_tokens,
        output_tokens=response.usage.output_tokens,
        cached_tokens=response.usage.cache_read_input_tokens,
    )
    return summary, usage


# Module-level, not per-call: created once and shared across every review
# this process runs, so the concurrency cap is a real *global* bound on
# concurrent Claude requests (protecting the account's actual rate limit)
# rather than a per-review bound that multiple simultaneous users could
# each independently max out (e.g. 2 concurrent reviews at the "per-call"
# version of this would fire 2x CLAUDE_MAX_CONCURRENT_REQUESTS at once).
_claude_semaphore = asyncio.Semaphore(config.CLAUDE_MAX_CONCURRENT_REQUESTS)


async def _generate_review_claude(
    caption_moments: list[CriticalMoment],
    all_moments: list[CriticalMoment],
    accuracy_pct: float,
    language: str,
) -> tuple[list[str], str, TokenUsage]:
    """Diamond-tier path. Returns (per-moment explanations for
    `caption_moments` in order, the closing game summary grounded in
    `all_moments`, combined token usage).

    Fires one Claude call per caption moment plus one summary call, all
    concurrently — bounded by the module-level semaphore above against
    Anthropic rate limits — instead of one sequential-turn batch call. Wall
    time tracks ceil(N / CLAUDE_MAX_CONCURRENT_REQUESTS) individual-call
    latencies rather than the sum of all N (e.g. 11 moments + 1 summary at
    the default limit of 5 is 3 sequential rounds, not 1 — raise the limit
    to shrink that further, now that it's a real global cap safe to raise
    without multiplying risk across concurrent users). This also isolates
    failures: one moment's call raising doesn't take down the others or the
    summary — it just falls back to the empty-explanation path each caller
    already handles (mistake fallback caption / skipped strength card /
    skipped summary message).

    Runs a cache-warming call first (see _warm_prompt_cache) so the N
    concurrent explanation calls below all read a warm system-prompt cache
    instead of racing to write it. This is a secondary saving, though — the
    task instructions that used to be resent in full on every one of the N
    *messages* (the actual dominant cost, ~9000 of ~9239 non-cached tokens
    measured in production before this) now live in
    build_explanation_system_prompt's cached system prompt instead, which
    is what actually fixed the blowup; the warm-up only guards the smaller
    remaining cache-write race on that system prompt.
    """
    if not caption_moments:
        return [], "", TokenUsage(0, 0, 0)

    semaphore = _claude_semaphore

    total_usage = await _warm_prompt_cache(language, semaphore)

    explanation_tasks = [
        _generate_moment_explanation(moment, language, semaphore) for moment in caption_moments
    ]
    summary_task = _generate_game_summary(all_moments, accuracy_pct, language, semaphore)

    results = await asyncio.gather(*explanation_tasks, summary_task, return_exceptions=True)
    *explanation_results, summary_result = results

    explanations = []
    for result in explanation_results:
        if isinstance(result, BaseException):
            explanations.append("")
            continue
        explanation, usage = result
        explanations.append(explanation)
        total_usage = total_usage + usage

    if isinstance(summary_result, BaseException):
        summary = ""
    else:
        summary, usage = summary_result
        total_usage = total_usage + usage

    return explanations, summary, total_usage


# --- Gemini path (Free/Ruby/Emerald) -----------------------------------
#
# A review's moments are split into several small parallel batches instead
# of either one call per moment (Claude's design — too many calls for a
# free-tier RPM budget) or one call for the whole game (the previous
# Gemini design — one failure loses the whole review's commentary, and a
# single call carrying 10+ moments has no headroom to isolate a bad one).
# Schema-constrained JSON output keys each explanation by (move_number,
# side) rather than relying on array order, so a model that reorders or
# drops an item still resolves correctly against its batch.


class _RateLimiter:
    """Sliding-window limiter: at most `limit` acquisitions in any trailing
    `period` seconds. This is NOT the same thing as the concurrency
    semaphore below — a concurrency cap alone doesn't bound *requests per
    minute* when individual calls finish in a few seconds (e.g. 12
    concurrent slots refilling every ~5s would let through 100+
    requests/minute). This class is what actually protects a provider's
    RPM quota; the semaphore is separately useful for bounding how many
    calls can be in flight at once across simultaneous users' reviews.
    """

    def __init__(self, limit: int, period_seconds: float):
        self._limit = limit
        self._period = period_seconds
        self._timestamps: collections.deque[float] = collections.deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] >= self._period:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._limit:
                    self._timestamps.append(now)
                    return
                wait_seconds = self._period - (now - self._timestamps[0])
            await asyncio.sleep(max(wait_seconds, 0.01))


# Module-level, not per-call: shared across every review this process
# runs (not just one review's own batches) — a review now fires several
# concurrent Gemini calls (ceil(N/_GEMINI_BATCH_SIZE) batches + 1 summary)
# instead of 1, so an unbounded fan-out across a handful of simultaneous
# users could blow past the API key's rate limit in seconds. 12 leaves
# headroom for 2-3 users' reviews to actually run concurrently (each
# peaking at 4-5 in-flight calls) instead of fully serializing to one
# review at a time.
_gemini_semaphore = asyncio.Semaphore(config.GEMINI_MAX_CONCURRENT_REQUESTS)

# The free-tier API key's real quota is 15 requests/minute — this is what
# enforces it (the semaphore above does not, see _RateLimiter's docstring).
_gemini_rate_limiter = _RateLimiter(limit=config.GEMINI_MAX_REQUESTS_PER_MINUTE, period_seconds=60.0)

# If waiting for a Gemini slot takes longer than this, on_queued (see
# _gemini_slot) fires so the caller can let the user know why nothing is
# happening yet, instead of the review just looking stuck.
_QUEUE_NOTICE_AFTER_SECONDS = 10.0


@contextlib.asynccontextmanager
async def _gemini_slot(on_queued: Callable[[], Awaitable[None]] | None):
    """Acquires one global concurrency slot plus one rate-limit token
    before letting a Gemini call proceed, releasing the slot on exit
    (including on exception) — both queue rather than error out when
    exhausted, by design (asyncio.Semaphore.acquire and _RateLimiter.acquire
    both just wait).
    """
    started = time.monotonic()
    await _gemini_semaphore.acquire()
    try:
        await _gemini_rate_limiter.acquire()
        waited = time.monotonic() - started
        if on_queued is not None and waited > _QUEUE_NOTICE_AFTER_SECONDS:
            try:
                await on_queued()
            except Exception:
                logger.exception("Gemini queue-notice callback failed")
        yield
    finally:
        _gemini_semaphore.release()


# 2-3 moments per batch keeps each call's own generation short (fast even
# on a busy Flash endpoint) while still amortizing the shared system
# prompt's overhead across more than one moment per call — an 11-moment
# review (a typical size) becomes ceil(11/3) = 4 batches, in the 4-5 range
# this was sized for.
_GEMINI_BATCH_SIZE = 3


def _chunk_moments(moments: list[CriticalMoment], target_size: int) -> list[list[CriticalMoment]]:
    """Splits into as-even-as-possible chunks of around `target_size` each,
    rather than greedily filling each chunk to the max and leaving a small
    remainder (e.g. 10 moments at target_size=3 becomes [3, 3, 2, 2], not
    [3, 3, 3, 1] — a lone straggler batch pays the same fixed per-call
    overhead as a full one for a third of the content).
    """
    if not moments:
        return []
    num_chunks = math.ceil(len(moments) / target_size)
    base, extra = divmod(len(moments), num_chunks)
    chunks = []
    start = 0
    for i in range(num_chunks):
        size = base + (1 if i < extra else 0)
        chunks.append(moments[start : start + size])
        start += size
    return chunks


# Initial estimate only, carried over from the same calibration this
# codebase used for the pre-parallel Claude batched call (see
# scripts/calibrate_caption_tokens.py) — Gemini's tokenizer isn't
# identical to Claude's, so this should be recalibrated against real
# usage_metadata once production numbers are in, same as that script does
# for Claude.
_GEMINI_AVG_EXPLANATION_TOKENS_WITH_HEADROOM = 120
_GEMINI_JSON_OVERHEAD_PER_MOMENT = 30
_GEMINI_JSON_WRAPPER_OVERHEAD = 10
_GEMINI_MIN_EXPLANATIONS_TOKENS = 300
_GEMINI_SUMMARY_MAX_TOKENS = 700


def _gemini_batch_calibrated_max_tokens(batch_size: int) -> int:
    per_moment = _GEMINI_AVG_EXPLANATION_TOKENS_WITH_HEADROOM + _GEMINI_JSON_OVERHEAD_PER_MOMENT
    return max(_GEMINI_MIN_EXPLANATIONS_TOKENS, _GEMINI_JSON_WRAPPER_OVERHEAD + per_moment * batch_size)


_GEMINI_EXPLANATIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "move_number": {"type": "integer"},
                    "side": {"type": "string", "enum": ["white", "black"]},
                    "explanation": {"type": "string"},
                },
                "required": ["move_number", "side", "explanation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["moments"],
    "additionalProperties": False,
}


def _gemini_system_instruction() -> str:
    # Role/style/corpus only, no task instructions — used for the summary
    # call, mirroring Claude's build_system_prompt(). Gemini's
    # system_instruction isn't a list of cache_control-tagged blocks like
    # Claude's; prefix caching here is automatic rather than something
    # this code has to request.
    return "\n\n".join([_ROLE_PROMPT, _STYLE_INSTRUCTIONS, _load_style_corpus()])


def _gemini_batch_task_instructions(lang_name: str) -> str:
    # Same mistake/strength guidance as Claude's _explanation_task_
    # instructions, plus the JSON-correlation instruction a batch needs
    # (Claude's per-moment calls don't, since there's only ever one moment
    # to key against there). Lives in *system_instruction*, not the
    # per-batch user message, precisely so Gemini's automatic prefix
    # caching has a chance to reuse it across this review's own 4-5
    # parallel batches (all identical) and across other reviews, instead
    # of paying for it fresh on every batch call — the same lesson the
    # Claude path already learned the hard way (see build_explanation_
    # system_prompt's history) applied here before it became a problem.
    return (
        "Для КАЖДОГО момента, описанного в пользовательском сообщении, "
        "напиши отдельное объяснение в своей манере — живой комментарий "
        "тренера, а не механический вердикт «ошибка/не ошибка», и НИКОГДА не "
        "оставляй объяснение пустым — оно должно быть содержательным, без "
        "исключений. "
        "Для ОШИБКИ: как и в примерах выше, можно сначала коротко отметить, что "
        "было хорошо в позиции или замысле перед сбоем, прежде чем объяснить сам "
        "промах — но объяснение должно оставаться правдивым: перед тобой реальная "
        "ошибка, не выдумывай похвалу самому ходу. "
        "Для СИЛЬНОГО ХОДА пиши по той же конкретной схеме, что и для ошибки: "
        "сначала — что именно даёт этот ход (материал, позиционный перевес, атаку "
        "на короля, инициативу), затем — почему это было не очевидно или сложно "
        "найти (например, единственный ход, спасающий партию, тихий манёвр без "
        "размена, который легко пропустить, или точный расчёт варианта). Не "
        "ограничивайся общими словами вроде «отличный ход» — назови конкретный "
        "эффект хода, так же предметно, как объясняешь ошибки. Это будет подпись "
        "под картинкой позиции в Telegram, поэтому объяснение должно быть "
        "коротким — 1-3 предложения по существу, без вступлений. "
        f"Пиши на языке: {lang_name}, сохраняя тот же стиль и манеру объяснения, что "
        "в примерах выше, даже если примеры на другом языке. Для форматирования "
        "используй **двойные звёздочки** для акцентов и `одинарные обратные кавычки` "
        "для нотации ходов (например, `Qxf6`) — это конвертируется в HTML на нашей "
        "стороне. Не используй заголовки, таблицы или другую разметку. Верни ровно "
        "один объект на каждый момент из пользовательского сообщения, в том же "
        'порядке — в поле "moments", с полями move_number, side и explanation, '
        "точно как указано у каждого момента во входных данных."
    )


def _gemini_batch_system_instruction(language: str) -> str:
    lang_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["en"])
    return "\n\n".join(
        [_ROLE_PROMPT, _STYLE_INSTRUCTIONS, _load_style_corpus(), _gemini_batch_task_instructions(lang_name)]
    )


def _gemini_batch_user_prompt(batch: list[CriticalMoment]) -> str:
    return (
        "Вот отмеченные моменты партии из этого батча — у каждого указан тип: "
        "ОШИБКА (потеря в оценке по движку больше 100 сантипешек) или СИЛЬНЫЙ ХОД "
        "(совпадение с лучшим ходом движка в непростой позиции, либо заметный "
        f"прирост оценки без простого взятия материала):\n\n{_format_moments(batch)}\n\n"
        "Напиши объяснения по инструкциям из системного промпта."
    )


def _usage_from_gemini_response(response) -> TokenUsage:
    usage_meta = response.usage_metadata
    prompt_tokens = (usage_meta.prompt_token_count or 0) if usage_meta else 0
    cached_tokens = (usage_meta.cached_content_token_count or 0) if usage_meta else 0
    return TokenUsage(
        # Gemini's prompt_token_count is the *total* prompt including any
        # cached portion (unlike Claude's response.usage.input_tokens,
        # which already excludes cache reads) — subtract cached_tokens here
        # so this field keeps the same "freshly billed at full price"
        # meaning across both providers, since it feeds the same
        # non_cached_input_tokens log field either way.
        input_tokens=max(0, prompt_tokens - cached_tokens),
        output_tokens=(usage_meta.candidates_token_count or 0) if usage_meta else 0,
        cached_tokens=cached_tokens,
    )


def _log_gemini_call_failure(exc: Exception, what: str, **context) -> None:
    # code/status/details are pulled out explicitly (not just left to
    # logger.exception's traceback line) because google.genai.errors.
    # APIError.details *is* the parsed response body — Google's own
    # "invalid argument" errors don't always name the offending field in
    # .message, but .details is the full JSON Google sent back, so
    # surfacing it separately guarantees it's visible even if a future
    # exception type formats str(exc) differently than APIError does.
    extra = " ".join(f"{key}={value}" for key, value in context.items())
    logger.exception(
        "%s failed (model=%s, %s): code=%s status=%s details=%r",
        what,
        config.GEMINI_MODEL,
        extra,
        getattr(exc, "code", None),
        getattr(exc, "status", None),
        getattr(exc, "details", None),
    )


# Explicit (not implicit) caching. Google's own docs are explicit that
# implicit caching has "no cost saving guarantee" — a hit depends on
# whether background infrastructure happens to already be holding a
# matching entry when a request lands, which is entirely outside this
# process's control. Production confirmed this the hard way: even a
# dedicated warm-up call, awaited to completion strictly *before* the
# batch fan-out started, still measured 0 cached_input_tokens — proof
# that our own call ordering can't influence server-side cache
# population/routing timing at all. Explicit caching is the one mechanism
# Google actually documents a *guaranteed* 90% discount for: create a
# named CachedContent resource once, then every call that references it
# via cached_content= gets the discount deterministically, not
# opportunistically.
@dataclass
class _GeminiCacheEntry:
    name: str
    good_until: float  # time.monotonic() deadline


# Mirrors the Claude path's 1h ephemeral cache_control TTL — shared across
# every review this process runs (not recreated per review), keyed by
# (kind, language) since the batch and summary calls use different system
# prompts (batch includes the per-moment task instructions, summary
# doesn't — see _gemini_batch_system_instruction vs _gemini_system_
# instruction) and each language needs its own cache entry.
_GEMINI_CACHE_TTL_SECONDS = 3600
# Recreate a bit before the real server-side expiry rather than racing it.
_GEMINI_CACHE_REFRESH_MARGIN_SECONDS = 120

_gemini_cache_entries: dict[tuple[str, str], _GeminiCacheEntry] = {}
_gemini_cache_locks: dict[tuple[str, str], asyncio.Lock] = collections.defaultdict(asyncio.Lock)

# caches.create() is documented to require a pinned model version rather
# than the "latest"-style alias generate_content itself accepts fine
# (e.g. config.GEMINI_MODEL="gemini-3.6-flash") — resolved lazily via
# models.get() once per process and reused, instead of guessing a version
# suffix that could itself 404. If resolution fails, falls back to using
# config.GEMINI_MODEL as-is for cache creation (today's behavior).
_gemini_cache_model_name: str | None = None
_gemini_cache_model_lock = asyncio.Lock()


async def _resolve_gemini_cache_model() -> str:
    global _gemini_cache_model_name
    if _gemini_cache_model_name is not None:
        return _gemini_cache_model_name
    async with _gemini_cache_model_lock:
        if _gemini_cache_model_name is not None:
            return _gemini_cache_model_name
        try:
            model_info = await gemini_client.aio.models.get(model=config.GEMINI_MODEL)
            resolved = model_info.name or config.GEMINI_MODEL
        except Exception as exc:
            logger.warning(
                "Could not resolve a pinned model name for Gemini caching (alias=%s): %s — "
                "using the alias as-is for caches.create, which may itself be why caching doesn't apply",
                config.GEMINI_MODEL,
                exc,
            )
            resolved = config.GEMINI_MODEL
        logger.info("Gemini cache model resolution: alias=%s -> %s", config.GEMINI_MODEL, resolved)
        _gemini_cache_model_name = resolved
        return resolved


# Set the first time any caches.create() call fails, for any reason — a
# free-tier API key gets TotalCachedContentStorageTokensPerModelFreeTier
# limit=0 (confirmed in production on two different models), a structural
# billing-tier restriction that retrying, or trying again on the next
# call, never resolves. Once tripped, _get_gemini_cache short-circuits to
# None immediately instead of repeating a doomed caches.create() attempt
# on every single batch/summary call — before this, that was adding
# minutes to a review's Gemini stage (5 calls x a failed creation attempt
# each, and — see gemini_service.py — the SDK retrying every one of those
# failures up to 5 times on its own before giving up). A rare false trip
# from a genuinely transient failure only costs caching for the rest of
# this process's life, not a crash — the bot already gets restarted on
# every deploy, which clears this back to False.
_gemini_cache_creation_unavailable = False


async def _get_gemini_cache(kind: str, language: str, system_instruction: str) -> str | None:
    """Returns a cached_content resource name for (kind, language),
    creating (or refreshing, once expired) it as needed. Returns None
    (never raises) on failure — callers fall back to sending
    system_instruction directly for that one call, same best-effort
    spirit as the rest of this module's Gemini calls.

    The per-key lock means that when several batches race to use a cache
    that doesn't exist yet, exactly one of them creates it (one extra
    billed call, amortized across every review for the next hour — not
    paid fresh per review) while the rest wait on the lock and then reuse
    it, rather than each independently creating a redundant cache.

    Logs every step (reuse / creation attempt / creation result) at INFO
    — this mechanism has failed silently twice already (implicit caching
    measuring 0% hit rate for reasons outside this process's visibility;
    a first cut of explicit caching that also produced 0% hits with no
    clear signal why), so the goal here is to make every step of "did we
    even try, did creation succeed, how big was what we cached" directly
    visible in the logs rather than inferred from token counts after the
    fact.
    """
    global _gemini_cache_creation_unavailable

    key = (kind, language)
    now = time.monotonic()
    entry = _gemini_cache_entries.get(key)
    if entry is not None and entry.good_until > now:
        logger.info(
            "Reusing Gemini cache kind=%s language=%s name=%s (good for another %.0fs)",
            kind,
            language,
            entry.name,
            entry.good_until - now,
        )
        return entry.name

    if _gemini_cache_creation_unavailable:
        return None

    async with _gemini_cache_locks[key]:
        # Re-check: another coroutine may have created/refreshed this (or
        # tripped the circuit breaker below) while this one waited on the
        # lock.
        entry = _gemini_cache_entries.get(key)
        now = time.monotonic()
        if entry is not None and entry.good_until > now:
            logger.info(
                "Reusing Gemini cache kind=%s language=%s name=%s (created by a concurrent caller "
                "while this one waited on the lock)",
                kind,
                language,
                entry.name,
            )
            return entry.name
        if _gemini_cache_creation_unavailable:
            return None

        cache_model = await _resolve_gemini_cache_model()
        logger.info(
            "Creating Gemini cache kind=%s language=%s model=%s system_instruction_chars=%d",
            kind,
            language,
            cache_model,
            len(system_instruction),
        )
        try:
            cache = await gemini_client.aio.caches.create(
                model=cache_model,
                config=genai_types.CreateCachedContentConfig(
                    system_instruction=system_instruction,
                    ttl=f"{_GEMINI_CACHE_TTL_SECONDS}s",
                ),
            )
        except Exception as exc:
            _log_gemini_call_failure(exc, "Gemini cache creation", kind=kind, language=language)
            _gemini_cache_creation_unavailable = True
            logger.warning(
                "Disabling Gemini explicit caching for the rest of this process — caches.create() "
                "failed (see the error above). If this is a billing/quota restriction (e.g. "
                "TotalCachedContentStorageTokensPerModelFreeTier limit=0 on the free tier), it won't "
                "resolve itself; restart the bot after enabling billing to try again."
            )
            return None

        cached_tokens = cache.usage_metadata.total_token_count if cache.usage_metadata else None
        logger.info(
            "Created Gemini cache kind=%s language=%s name=%s cached_tokens=%s ttl=%ds",
            kind,
            language,
            cache.name,
            cached_tokens,
            _GEMINI_CACHE_TTL_SECONDS,
        )

        _gemini_cache_entries[key] = _GeminiCacheEntry(
            name=cache.name,
            good_until=time.monotonic() + _GEMINI_CACHE_TTL_SECONDS - _GEMINI_CACHE_REFRESH_MARGIN_SECONDS,
        )
        return cache.name


def _invalidate_gemini_cache(kind: str, language: str) -> None:
    _gemini_cache_entries.pop((kind, language), None)


async def _generate_content_with_cache(
    kind: str, language: str, system_instruction: str, contents: str, **config_kwargs
):
    """generate_content, preferring an explicit cached_content reference
    for (kind, language) over resending system_instruction. If no cache
    is available, or the cached_content-based call itself fails (e.g. the
    entry was evicted server-side between our check and use), falls back
    to — or retries with — system_instruction sent directly, so a cache
    hiccup costs one extra call's worth of latency/tokens rather than
    failing the batch/summary outright.

    Logs whether cached_content was actually set on the request, and
    whether the response's own cached_content_token_count backs that up
    — a request that sent cached_content but got 0 cached tokens back
    means the API accepted the reference but didn't apply the discount,
    which is a distinct failure mode from "no cache exists yet" or
    "creation failed" and wouldn't otherwise be visible anywhere.
    """
    cache_name = await _get_gemini_cache(kind, language, system_instruction)
    if cache_name is not None:
        try:
            logger.info("Gemini %s call using cached_content=%s", kind, cache_name)
            response = await gemini_client.aio.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=contents,
                config=genai_types.GenerateContentConfig(cached_content=cache_name, **config_kwargs),
            )
        except Exception as exc:
            logger.warning(
                "Gemini call with cached_content=%s failed (%s), retrying without cache", cache_name, exc
            )
            _invalidate_gemini_cache(kind, language)
        else:
            actual_cached = (
                response.usage_metadata.cached_content_token_count if response.usage_metadata else None
            )
            if not actual_cached:
                logger.warning(
                    "Gemini %s call sent cached_content=%s but got cached_content_token_count=%s back "
                    "— the API did not apply the cache",
                    kind,
                    cache_name,
                    actual_cached,
                )
            else:
                logger.info(
                    "Gemini %s call confirmed cache hit: cached_content_token_count=%d",
                    kind,
                    actual_cached,
                )
            return response

    logger.info("Gemini %s call using system_instruction directly (no cache available)", kind)
    return await gemini_client.aio.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=contents,
        config=genai_types.GenerateContentConfig(system_instruction=system_instruction, **config_kwargs),
    )


async def _generate_explanations_batch_gemini(
    batch: list[CriticalMoment], language: str, on_queued: Callable[[], Awaitable[None]] | None
) -> tuple[dict[tuple[int, str], str], TokenUsage]:
    """One Gemini call per batch of _GEMINI_BATCH_SIZE moments. Best-effort
    like the rest of this module's Gemini calls: a failed or malformed
    response falls back to an empty dict rather than raising — the
    caller's fallback caption for mistakes and skipped strength cards
    absorbs this at the per-moment level, so losing one batch only loses
    that batch's couple of moments, not the whole review.
    """
    try:
        async with _gemini_slot(on_queued):
            response = await _generate_content_with_cache(
                kind="batch",
                language=language,
                system_instruction=_gemini_batch_system_instruction(language),
                contents=_gemini_batch_user_prompt(batch),
                max_output_tokens=_gemini_batch_calibrated_max_tokens(len(batch)),
                # Formulaic style-mimicry, not a reasoning task — same
                # rationale as thinking={"type": "disabled"} on the
                # Claude path. Gemini 3.x models replaced the numeric
                # thinking_budget with the string thinking_level enum
                # (minimal/low/medium/high); MINIMAL is the lowest
                # level 3.x exposes — there's no hard "off" anymore.
                thinking_config=genai_types.ThinkingConfig(
                    thinking_level=genai_types.ThinkingLevel.MINIMAL
                ),
                response_mime_type="application/json",
                response_json_schema=_GEMINI_EXPLANATIONS_SCHEMA,
            )
    except Exception as exc:
        _log_gemini_call_failure(exc, "Gemini explanations batch", batch_size=len(batch))
        return {}, TokenUsage(0, 0, 0)

    try:
        data = json.loads(response.text)
        explanations_by_key = {
            (item["move_number"], item["side"]): item["explanation"] for item in data["moments"]
        }
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        logger.warning(
            "Gemini explanations batch response didn't match the expected schema (model=%s): %.500r",
            config.GEMINI_MODEL,
            response.text,
        )
        explanations_by_key = {}

    return explanations_by_key, _usage_from_gemini_response(response)


async def _generate_game_summary_gemini(
    all_moments: list[CriticalMoment],
    accuracy_pct: float,
    language: str,
    on_queued: Callable[[], Awaitable[None]] | None,
) -> tuple[str, TokenUsage]:
    try:
        async with _gemini_slot(on_queued):
            response = await _generate_content_with_cache(
                kind="summary",
                language=language,
                system_instruction=_gemini_system_instruction(),
                contents=_summary_prompt(all_moments, accuracy_pct, language),
                max_output_tokens=_GEMINI_SUMMARY_MAX_TOKENS,
                thinking_config=genai_types.ThinkingConfig(
                    thinking_level=genai_types.ThinkingLevel.MINIMAL
                ),
            )
    except Exception as exc:
        _log_gemini_call_failure(exc, "Gemini summary call")
        return "", TokenUsage(0, 0, 0)

    summary = (response.text or "").strip()
    return summary, _usage_from_gemini_response(response)


async def _generate_review_gemini(
    caption_moments: list[CriticalMoment],
    all_moments: list[CriticalMoment],
    accuracy_pct: float,
    language: str,
    on_queued: Callable[[], Awaitable[None]] | None = None,
) -> tuple[list[str], str, TokenUsage]:
    """Free/Ruby/Emerald path. Same return shape as _generate_review_claude,
    firing caption_moments as several small parallel batches (see
    _GEMINI_BATCH_SIZE/_chunk_moments) plus a separate summary call, all
    through the process-global _gemini_semaphore/_gemini_rate_limiter (see
    _gemini_slot) — a review now makes ceil(N/3)+1 Gemini calls instead of
    1, so unbounded fan-out across simultaneous users would risk the API
    key's rate limit.

    Each batch/summary call goes through an explicit cached_content
    reference (see _generate_content_with_cache/_get_gemini_cache) rather
    than resending system_instruction — the first call for a given (kind,
    language) within the last hour pays to create the cache, every other
    call anywhere in the process reuses it at a guaranteed discount, so
    this review's own parallel batches benefit from each other exactly
    when the cache is still being created for the very first time (the
    per-key lock in _get_gemini_cache serializes that one creation), and
    unconditionally benefit from any other review's cache within the hour.
    """
    if not caption_moments:
        return [], "", TokenUsage(0, 0, 0)

    batches = _chunk_moments(caption_moments, _GEMINI_BATCH_SIZE)
    batch_tasks = [_generate_explanations_batch_gemini(batch, language, on_queued) for batch in batches]
    summary_task = _generate_game_summary_gemini(all_moments, accuracy_pct, language, on_queued)

    *batch_results, (summary, summary_usage) = await asyncio.gather(*batch_tasks, summary_task)

    total_usage = summary_usage
    explanations_by_key: dict[tuple[int, str], str] = {}
    for batch_explanations, usage in batch_results:
        explanations_by_key.update(batch_explanations)
        total_usage = total_usage + usage

    explanations = [explanations_by_key.get((m.move_number, m.side), "") for m in caption_moments]
    return explanations, summary, total_usage


# Tier -> API provider for review generation. Diamond is the only paid tier
# still on Claude; Free/Ruby/Emerald all route to the cheaper batched
# Gemini path. Falls back to "gemini" for any unrecognized tier (defensive
# only — subscription_service.TIER_ORDER is the source of truth for valid
# tier names and always includes these four).
_TIER_PROVIDER = {
    "free": "gemini",
    "ruby": "gemini",
    "emerald": "gemini",
    "diamond": "claude",
}


def model_for_tier(tier: str) -> str:
    """The model id actually used for a given tier's reviews — exposed so
    the caller can log which one ran without duplicating the tier->provider
    mapping above.
    """
    if _TIER_PROVIDER.get(tier, "gemini") == "claude":
        return config.CLAUDE_MODEL
    return config.GEMINI_MODEL


def calls_for_review(tier: str, moment_count: int) -> int:
    """How many API calls generate_review will actually make for a review
    with `moment_count` caption moments, on `tier`'s provider — for
    logging only, kept here rather than duplicated at the call site so it
    can't drift from the real batching logic above (_GEMINI_BATCH_SIZE is
    an implementation detail of this module, not something callers should
    need to know).

    Claude: one call per moment plus one summary call (_generate_review_
    claude). Gemini: ceil(moment_count / _GEMINI_BATCH_SIZE) batch calls
    plus one summary call (_generate_review_gemini/_chunk_moments) — e.g.
    10 moments is ceil(10/3) + 1 = 5. Doesn't count the occasional extra
    call this process makes to (re)create an explicit cache entry (see
    _get_gemini_cache) — that happens at most once per hour per (kind,
    language), not per review, so it isn't part of a review's own
    deterministic call count.
    """
    if moment_count == 0:
        return 0
    if _TIER_PROVIDER.get(tier, "gemini") == "claude":
        return moment_count + 1
    return math.ceil(moment_count / _GEMINI_BATCH_SIZE) + 1


async def generate_review(
    caption_moments: list[CriticalMoment],
    all_moments: list[CriticalMoment],
    accuracy_pct: float,
    language: str,
    tier: str,
    on_queued: Callable[[], Awaitable[None]] | None = None,
) -> tuple[list[str], str, TokenUsage]:
    """Returns (per-moment explanations for `caption_moments` in order, the
    closing game summary grounded in `all_moments`, combined token usage).

    Routes to the Claude or Gemini implementation above by `tier` — see the
    module docstring for why each tier uses the model it does, and
    model_for_tier if the caller also wants to log which model ran.

    `on_queued` is only meaningful on the Gemini path (ignored for Claude,
    which has its own separate, already-generous per-process semaphore) —
    invoked (possibly more than once, if more than one of this review's
    batches individually waits past the threshold) whenever a Gemini call
    ends up waiting more than _QUEUE_NOTICE_AFTER_SECONDS for a global
    slot, so the caller can tell the user why nothing is happening yet.
    Callers that only want one notice per review (e.g. a single Telegram
    message) should dedupe on their own side, same as handlers/game.py
    does.
    """
    if _TIER_PROVIDER.get(tier, "gemini") == "claude":
        return await _generate_review_claude(caption_moments, all_moments, accuracy_pct, language)
    return await _generate_review_gemini(caption_moments, all_moments, accuracy_pct, language, on_queued)


# --- /progress weaknesses-summary routing (all tiers) --------------------
#
# One flat request (a single text summary, no per-moment captions), but
# routed through the same _TIER_PROVIDER split as generate_review and the
# same Claude/Gemini plumbing (semaphore, rate limiter, explicit cache) —
# so its calls count against the same shared rate limits as game reviews
# instead of opening a second, unbounded set of Claude/Gemini requests.

_PROGRESS_CLAUDE_MAX_TOKENS = 4096
_PROGRESS_GEMINI_MAX_TOKENS = 1024


async def _summarize_weaknesses_claude(prompt: str) -> tuple[str, TokenUsage]:
    async with _claude_semaphore:
        response = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=_PROGRESS_CLAUDE_MAX_TOKENS,
            # Classification + prose, not a reasoning task — same rationale
            # as every other Claude call in this module.
            thinking={"type": "disabled"},
            system=build_system_prompt(),
            messages=[{"role": "user", "content": prompt}],
        )
    summary = "".join(block.text for block in response.content if block.type == "text").strip()
    usage = TokenUsage(
        input_tokens=response.usage.input_tokens + response.usage.cache_creation_input_tokens,
        output_tokens=response.usage.output_tokens,
        cached_tokens=response.usage.cache_read_input_tokens,
    )
    return summary, usage


async def _summarize_weaknesses_gemini(prompt: str, language: str) -> tuple[str, TokenUsage]:
    # kind="summary" deliberately reuses the same explicit-cache entry the
    # per-game closing summary already creates (_generate_game_summary_
    # gemini) — both send the identical role+style+corpus system prompt,
    # so a /progress call and a game review within the same hour share one
    # cache write instead of paying for two.
    try:
        async with _gemini_slot(None):
            response = await _generate_content_with_cache(
                kind="summary",
                language=language,
                system_instruction=_gemini_system_instruction(),
                contents=prompt,
                max_output_tokens=_PROGRESS_GEMINI_MAX_TOKENS,
                thinking_config=genai_types.ThinkingConfig(
                    thinking_level=genai_types.ThinkingLevel.MINIMAL
                ),
            )
    except Exception as exc:
        _log_gemini_call_failure(exc, "Gemini progress summary call")
        return "", TokenUsage(0, 0, 0)

    summary = (response.text or "").strip()
    return summary, _usage_from_gemini_response(response)


async def generate_progress_summary(prompt: str, language: str, tier: str) -> tuple[str, TokenUsage]:
    """Routes /progress's recurring-weaknesses summary by the same
    tier->provider split as generate_review (see _TIER_PROVIDER): Diamond
    stays on Claude, Free/Ruby/Emerald go through the Gemini path —
    instead of always using Claude regardless of tier, which is what this
    used to do.
    """
    if _TIER_PROVIDER.get(tier, "gemini") == "claude":
        return await _summarize_weaknesses_claude(prompt)
    return await _summarize_weaknesses_gemini(prompt, language)
