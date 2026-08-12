"""Turns a game's critical moments into per-moment Telegram-ready explanations,
written in the style captured by chess_style_corpus.md, via the Claude API
(model: claude-sonnet-5).
"""
import functools
import json
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


_REVIEW_SCHEMA = {
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
        "summary": {"type": "string"},
    },
    "required": ["moments", "summary"],
    "additionalProperties": False,
}

# Recalibrated against the current chess_style_corpus.md: 38 per-move
# annotations, average 79.8 characters but up to 160 for the longest ones —
# the previous calibration (72.9 avg, no allowance for the long tail) was
# too tight for real per-moment variance, and got worse once the prompt
# started asking for compound explanations (what was good + what went
# wrong, for mistakes) that tend to run longer than a single bare corpus
# annotation. This is why strength/mistake captions were coming back empty
# in production: later items in a 12-moment batch ran the response out of
# budget, and the model closed out the JSON with an empty "explanation"
# rather than leaving it malformed.
#
# ~160 chars at a conservative ~2.2 chars/token for Cyrillic -> ~73
# tokens for the longest real content alone, rounded up generously for the
# compound-instruction overhead -> 120. Recalibrate precisely with
# `scripts/calibrate_caption_tokens.py` (uses the real tokenizer via
# messages.count_tokens) once a real ANTHROPIC_API_KEY is available — these
# are a conservative manual estimate, not a measured one.
_AVG_EXPLANATION_TOKENS_WITH_HEADROOM = 120
_JSON_OVERHEAD_PER_MOMENT = 30  # field names + punctuation for one array item
_JSON_WRAPPER_OVERHEAD = 10  # the {"moments": [...]} envelope
_MIN_MAX_TOKENS = 400


def _calibrated_max_tokens(moment_count: int) -> int:
    per_moment = _AVG_EXPLANATION_TOKENS_WITH_HEADROOM + _JSON_OVERHEAD_PER_MOMENT
    return max(_MIN_MAX_TOKENS, _JSON_WRAPPER_OVERHEAD + per_moment * moment_count)


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int
    cached_tokens: int


# The corpus's own closing blocks are short — measured at 145-180 characters
# total across all 8 examples (one evaluative phrase + 3-4 one-line notes).
# 500 was already generous for that content alone, yet real runs were
# truncating mid-sentence — the likely cause is the same one documented on
# the explanations call below: without `thinking` explicitly disabled, a
# call has no headroom carved out for it and no guarantee thinking tokens
# wouldn't eat into the budget before any visible text got written. Fixed by
# disabling thinking, plus a bump for margin and a tighter prompt so the
# model doesn't try to restate the whole game instead of just the closing
# block.
_SUMMARY_MAX_TOKENS = 700


async def generate_review(
    caption_moments: list[CriticalMoment],
    all_moments: list[CriticalMoment],
    accuracy_pct: float,
    language: str,
) -> tuple[list[str], str, TokenUsage]:
    """Returns (per-moment explanations for `caption_moments` in order, the
    closing game summary grounded in `all_moments`, token usage), from a
    single Claude call.

    Merged from two sequential calls (explanations, then summary) into one —
    production timing showed the pair costing ~23s combined, and a chunk of
    that was the second call's own fixed round-trip/prompt-processing
    overhead rather than generation time. The trade-off: a malformed or
    truncated response now loses both outputs together instead of only one
    (see the parsing fallback below) — accepted since a schema-constrained
    JSON response is already the rare-failure case, not the common one.
    """
    if not caption_moments:
        return [], "", TokenUsage(0, 0, 0)

    lang_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["en"])

    if len(all_moments) == len(caption_moments):
        summary_context = "Для итоговой сводки опирайся на тот же список моментов, что и выше."
    else:
        # all_moments is the full, uncapped list of flagged moments (before
        # select_top_moments trims it to the handful that get individual
        # captions) — the summary should still be grounded in everything
        # that happened, not just the subset shown as photo cards.
        summary_context = (
            "Для итоговой сводки, в отличие от индивидуальных объяснений выше, "
            "опирайся на ПОЛНЫЙ список отмеченных моментов партии (включая те, "
            f"что не вошли в список для отдельных объяснений):\n\n{_format_moments(all_moments)}"
        )

    user_prompt = (
        "Вот отмеченные моменты партии, по порядку — у каждого указан тип: "
        "ОШИБКА (потеря в оценке по движку больше 100 сантипешек) или СИЛЬНЫЙ ХОД "
        "(совпадение с лучшим ходом движка в непростой позиции, либо заметный "
        f"прирост оценки без простого взятия материала):\n\n{_format_moments(caption_moments)}\n\n"
        "ЗАДАЧА 1 — для КАЖДОГО момента из списка выше напиши отдельное "
        "объяснение в своей манере — живой комментарий тренера, а не "
        "механический вердикт «ошибка/не ошибка», и НИКОГДА не оставляй "
        "объяснение пустым — у каждого момента должно быть содержательное "
        "объяснение, без исключений. "
        "Для ОШИБОК: как и в примерах выше, можно сначала коротко отметить, что "
        "было хорошо в позиции или замысле перед сбоем, прежде чем объяснить сам "
        "промах — но объяснение должно оставаться правдивым: перед тобой реальная "
        "ошибка, не выдумывай похвалу самому ходу. "
        "Для СИЛЬНЫХ ХОДОВ пиши по той же конкретной схеме, что и для ошибок: "
        "сначала — что именно даёт этот ход (материал, позиционный перевес, атаку "
        "на короля, инициативу), затем — почему это было не очевидно или сложно "
        "найти (например, единственный ход, спасающий партию, тихий манёвр без "
        "размена, который легко пропустить, или точный расчёт варианта). Не "
        "ограничивайся общими словами вроде «отличный ход» — назови конкретный "
        "эффект хода, так же предметно, как объясняешь ошибки. Каждое объяснение "
        "будет подписью под картинкой позиции в Telegram, поэтому оно должно быть "
        "коротким — 1-3 предложения по существу, без вступлений. Для форматирования "
        "используй **двойные звёздочки** для акцентов и `одинарные обратные кавычки` "
        "для нотации ходов (например, `Qxf6`) — это конвертируется в HTML на нашей "
        "стороне. Не используй заголовки, таблицы или другую разметку. Верни ровно "
        "один объект на каждый момент из списка выше, в том же порядке — в поле "
        '"moments".\n\n'
        f"ЗАДАЧА 2 — точность партии по движку: {accuracy_pct:.1f}%. {summary_context}\n\n"
        'Напиши короткую итоговую сводку партии в поле "summary" — тот блок, '
        "которым заканчивается каждый разбор в примерах выше (после «По общей "
        "оценке у тебя:»), и ничего больше: без вступления, без пересказа "
        "отдельных ходов, без заключения после сводки. Сначала оценочная фраза "
        f"вместе с процентом точности ({accuracy_pct:.1f}%), затем по одной "
        "короткой строке (одно-два предложения, не абзац) на дебют, на тактику/"
        "стратегию и на эндшпиль, опираясь на то, что реально было в партии. В "
        "примерах выше эта сводка целиком — 3-5 коротких строк, ориентируйся на "
        "тот же объём. Обычный текст, без разметки и без списков, в своей "
        "обычной манере.\n\n"
        f"Обе задачи пиши на языке: {lang_name}, сохраняя тот же стиль и манеру, "
        "что в примерах выше, даже если примеры на другом языке."
    )

    response = await client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=_calibrated_max_tokens(len(caption_moments)) + _SUMMARY_MAX_TOKENS,
        # Formulaic style-mimicry, not a reasoning task, and the calibrated
        # max_tokens above has no headroom for unpredictable thinking spend —
        # disabling it keeps the budget entirely for the visible JSON output.
        thinking={"type": "disabled"},
        # No sampling controls on this model: claude-sonnet-5 rejects
        # temperature/top_p/top_k entirely (400 invalid_request_error) — there
        # is no server-side knob for determinism here. The empty-explanation
        # bug this used to guard against (observed in production for
        # strength-type moments) is instead addressed by the "never leave
        # explanation empty" directive and the concrete, symmetric
        # mistake/strength instructions above — prompt-only determinism.
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": _REVIEW_SCHEMA},
        },
        system=build_system_prompt(),
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = next(block.text for block in response.content if block.type == "text")
    try:
        data = json.loads(text)
        explanations_by_key = {
            (item["move_number"], item["side"]): item["explanation"] for item in data["moments"]
        }
        summary = data["summary"].strip()
    except (json.JSONDecodeError, KeyError, TypeError):
        # A response cut off mid-JSON (tight max_tokens, longer-than-usual
        # explanations) shouldn't crash the whole review — fall back to the
        # per-moment default caption and a skipped summary message in the
        # handler instead.
        explanations_by_key = {}
        summary = ""

    explanations = [
        explanations_by_key.get((m.move_number, m.side), "") for m in caption_moments
    ]

    usage = TokenUsage(
        input_tokens=response.usage.input_tokens + response.usage.cache_creation_input_tokens,
        output_tokens=response.usage.output_tokens,
        cached_tokens=response.usage.cache_read_input_tokens,
    )
    return explanations, summary, usage
