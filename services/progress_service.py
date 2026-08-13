"""Classifies a user's critical moments from the last 30 days into recurring
weakness categories (tactics / endgame / opening / positional understanding)
and summarizes the top-3 in plain text, via the Claude API (model:
claude-sonnet-5). Reuses commentary_service's coach persona and cached style
corpus so the voice stays consistent with per-game reviews.
"""
import config
from services.claude_service import client
from services.commentary_service import build_system_prompt

_LANGUAGE_NAMES = {"ru": "русском", "en": "английском"}

_MAX_TOKENS = 4096


def _format_moments(moments) -> str:
    lines = []
    for m in moments:
        lines.append(
            f"- Ход {m['move_number']}: контекст `{m['context_san']}`; "
            f"сыгранный ход — `{m['move_san']}` (потеря {m['cp_loss']} сп)."
        )
    return "\n".join(lines)


async def summarize_weaknesses(moments, language: str) -> str:
    """Classifies the given critical moments into tactics/endgame/opening/
    positional categories in one call and returns a plain-text summary of
    the top-3 most recurring ones.
    """
    lang_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["en"])

    user_prompt = (
        "Вот все критические ошибки ученика за последние 30 дней, из разных "
        f"партий:\n\n{_format_moments(moments)}\n\n"
        "Классифицируй каждую ошибку по одной из категорий: тактика, эндшпиль, "
        "дебютные ошибки, позиционное непонимание. Определи три категории, "
        "которые повторяются чаще всего, и опиши их ученику простым текстом — "
        "обычными предложениями, без списков и без разметки, в своей манере, "
        f"как в примерах выше. Пиши на языке: {lang_name}, сохраняя тот же "
        "стиль и манеру объяснения, что в примерах выше, даже если примеры на "
        "другом языке."
    )

    response = await client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=_MAX_TOKENS,
        # Classification + prose, not a reasoning task — same rationale as
        # every Claude call in commentary_service.py. This was the one
        # call left without it (this file predates that fix), and without
        # it the model can spend the whole max_tokens budget on invisible
        # thinking with nothing left for visible output — response.content
        # then has no "text" blocks at all, so the join below silently
        # returns "" instead of raising, and the bot posts the
        # progress_header with a blank body after it.
        thinking={"type": "disabled"},
        system=build_system_prompt(),
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")
