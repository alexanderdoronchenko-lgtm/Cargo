"""Turns a game's critical moments into a Telegram-ready review, written in the
style captured by chess_style_corpus.md, via the Claude API (model: claude-sonnet-5).
"""
import functools

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


async def generate_game_review(critical_moments: list[CriticalMoment], language: str) -> str:
    """Returns Telegram-ready Markdown text reviewing the game's critical moments."""
    lang_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["en"])

    user_prompt = (
        "Вот критические моменты партии (ходы, где потеря в оценке по движку "
        f"превысила 100 сантипешек):\n\n{_format_moments(critical_moments)}\n\n"
        "Разбери эти моменты в своей манере — тон, длина фраз, обороты речи, как в "
        f"примерах выше. Ответь на языке: {lang_name}, сохраняя тот же стиль и манеру "
        "объяснения, что в примерах выше, даже если примеры на другом языке. Будь по "
        "существу, без длинных вступлений — как в примерах. Используй Markdown-разметку, "
        "поддерживаемую Telegram: **жирный** для акцентов, `код` для нотации ходов "
        "(например, `Qxf6`). Не используй заголовки, таблицы или другую разметку."
    )

    response = await client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=16000,
        output_config={"effort": "medium"},
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")
