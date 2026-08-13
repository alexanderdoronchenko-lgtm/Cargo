"""Classifies a user's critical moments from the last 30 days into recurring
weakness categories (tactics / endgame / opening / positional understanding)
and summarizes the top-3 in plain text. Routed by subscription tier through
commentary_service.generate_progress_summary — Diamond via Claude,
Free/Ruby/Emerald via Gemini, the same split game reviews use — and reuses
commentary_service's coach persona and cached style corpus so the voice
stays consistent with per-game reviews.
"""
from services.commentary_service import TokenUsage, generate_progress_summary

_LANGUAGE_NAMES = {"ru": "русском", "en": "английском"}


def _format_moments(moments) -> str:
    lines = []
    for m in moments:
        lines.append(
            f"- Ход {m['move_number']}: контекст `{m['context_san']}`; "
            f"сыгранный ход — `{m['move_san']}` (потеря {m['cp_loss']} сп)."
        )
    return "\n".join(lines)


def _build_prompt(moments, language: str) -> str:
    lang_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["en"])
    return (
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


async def summarize_weaknesses(moments, language: str, tier: str) -> tuple[str, TokenUsage]:
    """Classifies the given critical moments into tactics/endgame/opening/
    positional categories in one call and returns a plain-text summary of
    the top-3 most recurring ones, via whichever provider `tier` routes to
    (see commentary_service.generate_progress_summary).
    """
    prompt = _build_prompt(moments, language)
    return await generate_progress_summary(prompt, language, tier)
