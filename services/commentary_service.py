"""Turns a game's critical moments into per-moment Telegram-ready explanations,
written in the style captured by chess_style_corpus.md, via the Claude API
(model: claude-sonnet-5).
"""
import asyncio
import functools
from dataclasses import dataclass

import config
from services.claude_service import client
from services.engine_service import TYPE_STRENGTH, CriticalMoment

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


async def _warm_prompt_cache(semaphore: asyncio.Semaphore) -> TokenUsage:
    """Writes the system prompt's cache entry with a single throwaway call
    *before* the real fan-out in generate_review, so every one of the N
    concurrent calls below reads an already-warm cache instead of racing to
    write it themselves.

    A cache entry only becomes readable once some request has finished
    writing it — firing N calls with an identical system prompt at the same
    instant (as generate_review's asyncio.gather does) means several of
    them start before any entry exists, so each pays full (cache-creation)
    price for the ~3800-token corpus independently. Confirmed in
    production: 9239 non-cached input tokens across one 10-call batch is
    almost exactly 2-3 redundant writes of that corpus (3778 tokens each),
    not per-call game context — each call's own user content is already
    just one moment's data (~60-100 tokens), not the whole game.

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
                system=build_system_prompt(),
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
    """
    lang_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["en"])

    user_prompt = (
        "Вот отмеченный момент партии — указан его тип: ОШИБКА (потеря в "
        "оценке по движку больше 100 сантипешек) или СИЛЬНЫЙ ХОД (совпадение "
        "с лучшим ходом движка в непростой позиции, либо заметный прирост "
        f"оценки без простого взятия материала):\n\n{_format_moments([moment])}\n\n"
        "Напиши отдельное объяснение в своей манере — живой комментарий "
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
            # the concrete mistake/strength instructions above.
            system=build_system_prompt(),
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
    lang_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["en"])

    user_prompt = (
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

    async with semaphore:
        response = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=_SUMMARY_MAX_TOKENS,
            thinking={"type": "disabled"},
            system=build_system_prompt(),
            messages=[{"role": "user", "content": user_prompt}],
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


async def generate_review(
    caption_moments: list[CriticalMoment],
    all_moments: list[CriticalMoment],
    accuracy_pct: float,
    language: str,
) -> tuple[list[str], str, TokenUsage]:
    """Returns (per-moment explanations for `caption_moments` in order, the
    closing game summary grounded in `all_moments`, combined token usage).

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
    concurrent calls below all read a warm system-prompt cache instead of
    racing to write it — without this, several of them miss the cache
    simultaneously and each pays full price for the ~3800-token corpus
    independently (confirmed in production: 9239 non-cached input tokens on
    one 10-call batch, consistent with 2-3 redundant writes).
    """
    if not caption_moments:
        return [], "", TokenUsage(0, 0, 0)

    semaphore = _claude_semaphore

    total_usage = await _warm_prompt_cache(semaphore)

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
