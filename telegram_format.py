"""Converts the lightweight formatting Claude is asked to use (**bold**,
`code`) into Telegram's HTML parse mode — the bot's default (see bot.py).

Plain Markdown (**bold**) does not render under parse_mode=HTML; Telegram
would show the literal asterisks. This escapes the raw text first (so any
incidental &, <, > in model output can never be misparsed as markup), then
layers in real <b>/<code> tags only for markers that appear as complete,
matched pairs — an unmatched ** or ` is left as harmless literal text
instead of producing an unbalanced tag.
"""
import html
import re

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_CODE_RE = re.compile(r"`([^`\n]+?)`")
_TAG_RE = re.compile(r"</?(?:b|code)>")


def markdown_to_html(text: str) -> str:
    escaped = html.escape(text)
    escaped = _BOLD_RE.sub(lambda m: f"<b>{m.group(1)}</b>", escaped)
    escaped = _CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", escaped)
    return escaped


def truncate_html(text: str, max_length: int) -> str:
    """Truncates HTML produced by markdown_to_html() to at most max_length
    characters without ever leaving an unbalanced tag. Converted text is
    usually already short, so this only bites on unusually long output:
    first try dropping our own tags (removes their overhead), then hard-cut
    the now tag-free text.
    """
    if len(text) <= max_length:
        return text

    plain = _TAG_RE.sub("", text)
    if len(plain) <= max_length:
        return plain

    return plain[: max_length - 1].rstrip() + "…"
