"""Turns a game's critical moments into per-moment Telegram-ready explanations,
written in the style captured by chess_style_corpus.md, via the Claude API
(model: claude-sonnet-5).
"""
import functools
import json
from dataclasses import dataclass

import config
from services.claude_service import client
from services.engine_service import CriticalMoment

_CORPUS_PATH = config.BASE_DIR / "chess_style_corpus.md"

_LANGUAGE_NAMES = {"ru": "русском", "en": "английском"}

_ROLE_PROMPT = (
    "Ты — шахматный тренер, гроссмейстер. Ты разбираешь партии своих учеников "
    "после игры и объясняешь им ошибки: где ход был точным, где — зевком, где — "
    "стратегической неточностью. Твоя речь живая и человеческая, а не сухой отчёт "
    "движка."
)

_STYLE_INSTRUCTIONS = (
    "Ниже — корпус примеров твоих прошлых разборов партий. Это ПРИМЕРЫ ТОНА И "
    "МАНЕРЫ: как ты формулируешь мысли, длину фраз, обороты речи, баланс похвалы и "
    "критики, стиль итоговой оценки в конце партии. Это НЕ образец языка ответа — "
    "корпус написан по-русски, но отвечать ты будешь на языке, указанном в запросе "
    "пользователя, даже если он отличается от языка примеров. Копируй манеру "
    "объяснения, а не язык."
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
        return "Критических моментов (потеря более 100 сантипешек) в партии не найдено."

    lines = []
    for m in moments:
        side = "белые" if m.side == "white" else "чёрные"
        lines.append(
            f"- Ход {m.move_number} ({side}): контекст `{m.context_san}`; "
            f"критический ход — `{m.move_san}`, лучший ход по движку — "
            f"`{m.best_move_san}`. Оценка до хода: {m.score_before_cp:+d} сп, "
            f"после: {m.score_after_cp:+d} сп (потеря {m.cp_loss} сп)."
        )
    return "\n".join(lines)


_EXPLANATIONS_SCHEMA = {
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
        }
    },
    "required": ["moments"],
    "additionalProperties": False,
}

# Calibrated against chess_style_corpus.md: 39 per-move annotations, average
# 72.9 characters, approximated at ~2.5 chars/token for Cyrillic text (a
# conservative ratio — the real Claude tokenizer usually does a bit better)
# -> ~29 tokens/annotation, +20% headroom -> ~35. Recalibrate precisely with
# `scripts/calibrate_caption_tokens.py` (uses the real tokenizer via
# messages.count_tokens) once a real ANTHROPIC_API_KEY is available.
_AVG_EXPLANATION_TOKENS_WITH_HEADROOM = 35
_JSON_OVERHEAD_PER_MOMENT = 20  # field names + punctuation for one array item
_JSON_WRAPPER_OVERHEAD = 10  # the {"moments": [...]} envelope
_MIN_MAX_TOKENS = 150


def _calibrated_max_tokens(moment_count: int) -> int:
    per_moment = _AVG_EXPLANATION_TOKENS_WITH_HEADROOM + _JSON_OVERHEAD_PER_MOMENT
    return max(_MIN_MAX_TOKENS, _JSON_WRAPPER_OVERHEAD + per_moment * moment_count)


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int
    cached_tokens: int


async def generate_moment_explanations(
    critical_moments: list[CriticalMoment], language: str
) -> tuple[list[str], TokenUsage]:
    """Returns one Telegram-ready Markdown explanation per critical moment (in
    order), plus the token usage actually billed for the call.
    """
    if not critical_moments:
        return [], TokenUsage(0, 0, 0)

    lang_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["en"])

    user_prompt = (
        "Вот критические моменты партии (ходы, где потеря в оценке по движку "
        f"превысила 100 сантипешек), по порядку:\n\n{_format_moments(critical_moments)}\n\n"
        "Для КАЖДОГО момента напиши отдельное объяснение в своей манере — тон, "
        "обороты речи, баланс похвалы и критики, как в примерах выше. Это будет "
        "подпись под картинкой позиции в Telegram, поэтому объяснение должно быть "
        "коротким — 1-3 предложения по существу, без вступлений. "
        f"Пиши на языке: {lang_name}, сохраняя тот же стиль и манеру объяснения, что "
        "в примерах выше, даже если примеры на другом языке. Для форматирования "
        "используй **двойные звёздочки** для акцентов и `одинарные обратные кавычки` "
        "для нотации ходов (например, `Qxf6`) — это конвертируется в HTML на нашей "
        "стороне. Не используй заголовки, таблицы или другую разметку. Верни ровно "
        "один объект на каждый момент из списка выше, в том же порядке."
    )

    response = await client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=_calibrated_max_tokens(len(critical_moments)),
        # This is formulaic style-mimicry, not a reasoning task, and the tight
        # max_tokens above has no headroom for unpredictable thinking spend —
        # disabling it keeps the budget entirely for the visible JSON output
        # (and avoids paying for thinking tokens at all).
        thinking={"type": "disabled"},
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": _EXPLANATIONS_SCHEMA},
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
    except (json.JSONDecodeError, KeyError, TypeError):
        # A response cut off mid-JSON (tight max_tokens, longer-than-usual
        # explanations) shouldn't crash the whole review — fall back to the
        # per-moment default caption in the handler instead.
        explanations_by_key = {}

    explanations = [
        explanations_by_key.get((m.move_number, m.side), "") for m in critical_moments
    ]

    usage = TokenUsage(
        input_tokens=response.usage.input_tokens + response.usage.cache_creation_input_tokens,
        output_tokens=response.usage.output_tokens,
        cached_tokens=response.usage.cache_read_input_tokens,
    )
    return explanations, usage
