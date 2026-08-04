"""Loads translated strings from locales/*.json and exposes a lookup helper."""
import json
from pathlib import Path

_LOCALES_DIR = Path(__file__).resolve().parent / "locales"
DEFAULT_LANG = "en"
SUPPORTED_LANGS = ("ru", "en")

_translations: dict[str, dict[str, str]] = {
    lang: json.loads((_LOCALES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    for lang in SUPPORTED_LANGS
}


def resolve_lang(language_code: str | None) -> str:
    """Maps a Telegram language_code to a supported bot language."""
    return "ru" if language_code == "ru" else DEFAULT_LANG


def t(key: str, lang: str, **kwargs) -> str:
    strings = _translations.get(lang, _translations[DEFAULT_LANG])
    template = strings.get(key, _translations[DEFAULT_LANG].get(key, key))
    return template.format(**kwargs) if kwargs else template
