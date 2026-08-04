"""Turns a game's critical moments into per-moment Telegram-ready explanations,
written in the style captured by chess_style_corpus.md, via the Claude API
(model: claude-sonnet-5).
"""
import functools
import json

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


def _build_system_prompt() -> list[dict]:
    return [
        {"type": "text", "text": _ROLE_PROMPT},
        {"type": "text", "text": _STYLE_INSTRUCTIONS},
        {
            "type": "text",
            "text": _load_style_corpus(),
            "cache_control": {"type": "ephemeral"},
        },
    ]


def _format_moments(moments: list[CriticalMoment]) -> str:
    if not moments:
        return "Критических моментов (потеря более 100 сантипешек) в партии не найдено."

    lines = []
    for m in moments:
        side = "белые" if m.side == "white" else "чёрные"
        lines.append(
            f"- Ход {m.move_number} ({side}): сыграно `{m.move_san}`, "
            f"лучший ход по движку — `{m.best_move_san}`. "
            f"Оценка до хода: {m.score_before_cp:+d} сп, после: {m.score_after_cp:+d} сп "
            f"(потеря {m.cp_loss} сп)."
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


async def generate_moment_explanations(
    critical_moments: list[CriticalMoment], language: str
) -> list[str]:
    """Returns one Telegram-ready Markdown explanation per critical moment, in order."""
    if not critical_moments:
        return []

    lang_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["en"])

    user_prompt = (
        "Вот критические моменты партии (ходы, где потеря в оценке по движку "
        f"превысила 100 сантипешек), по порядку:\n\n{_format_moments(critical_moments)}\n\n"
        "Для КАЖДОГО момента напиши отдельное объяснение в своей манере — тон, "
        "обороты речи, баланс похвалы и критики, как в примерах выше. Это будет "
        "подпись под картинкой позиции в Telegram, поэтому объяснение должно быть "
        "коротким — 1-3 предложения по существу, без вступлений. "
        f"Пиши на языке: {lang_name}, сохраняя тот же стиль и манеру объяснения, что "
        "в примерах выше, даже если примеры на другом языке. Используй Markdown-разметку, "
        "поддерживаемую Telegram: **жирный** для акцентов, `код` для нотации ходов "
        "(например, `Qxf6`). Не используй заголовки или таблицы. Верни ровно один "
        "объект на каждый момент из списка выше, в том же порядке."
    )

    response = await client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=16000,
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": _EXPLANATIONS_SCHEMA},
        },
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)

    explanations = {
        (item["move_number"], item["side"]): item["explanation"] for item in data["moments"]
    }
    return [explanations.get((m.move_number, m.side), "") for m in critical_moments]
