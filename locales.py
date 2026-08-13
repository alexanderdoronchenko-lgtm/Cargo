"""Loads translated strings from locales/*.json and exposes a lookup helper."""
import html
import json
from pathlib import Path

_LOCALES_DIR = Path(__file__).resolve().parent / "locales"
DEFAULT_LANG = "en"
SUPPORTED_LANGS = ("ru", "en")

_translations: dict[str, dict[str, str]] = {
    lang: json.loads((_LOCALES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    for lang in SUPPORTED_LANGS
}


def _check_no_raw_angle_brackets() -> None:
    """Every message the bot sends goes out under Telegram's HTML
    parse_mode (see bot.py) by default. Locale templates are always plain
    text — the bot's one legitimate source of Telegram HTML markup
    (Claude's move captions, via **bold**/`code`) goes through
    telegram_format.markdown_to_html instead, a separate path that
    escapes raw text first and only emits tags it generates itself. A
    literal "<" or ">" sitting in a locale template is therefore always a
    mistake, never intentional markup — and an expensive one to leave in,
    since Telegram doesn't reject it until the moment a real user
    triggers that exact string (TelegramBadRequest: can't parse
    entities), not when the string was written. This is exactly what
    shipped in start_greeting: a "<username>"-style placeholder that
    Telegram tried, and failed, to parse as an HTML tag.

    Runs at import time — which includes every bot startup, and a bare
    `python -c "import locales"` needs no .env/config at all — so a bad
    template fails loudly and immediately instead of waiting for a user
    to hit it in production.
    """
    offenders = [
        f"{lang}.{key}"
        for lang, strings in _translations.items()
        for key, template in strings.items()
        if "<" in template or ">" in template
    ]
    if offenders:
        raise ValueError(
            "Locale templates contain a literal '<' or '>', which Telegram's HTML "
            "parse_mode will try to parse as markup and likely reject: "
            + ", ".join(offenders)
            + '. Rewrite without angle brackets (e.g. "/chesscom your_username" '
            'instead of "/chesscom <username>").'
        )


_check_no_raw_angle_brackets()


def resolve_lang(language_code: str | None) -> str:
    """Maps a Telegram language_code to a supported bot language."""
    return "ru" if language_code == "ru" else DEFAULT_LANG


def t(key: str, lang: str, **kwargs) -> str:
    strings = _translations.get(lang, _translations[DEFAULT_LANG])
    template = strings.get(key, _translations[DEFAULT_LANG].get(key, key))
    if not kwargs:
        return template
    # Every interpolated value ends up in a message sent under Telegram's
    # HTML parse_mode — escaping here, once, covers every current and
    # future t(...) call site (e.g. a /chesscom username is arbitrary
    # user-typed text, not just a Telegram @username) instead of relying
    # on each call site to remember to do it. Non-strings (int/float
    # counts, prices, limits) pass through as-is — they can't carry markup.
    safe_kwargs = {k: html.escape(v) if isinstance(v, str) else v for k, v in kwargs.items()}
    return template.format(**safe_kwargs)
