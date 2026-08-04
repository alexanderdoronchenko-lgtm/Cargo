"""Visual smoke test for telegram_format.markdown_to_html() — no bot token or
network access needed. Run it and eyeball the output; it also does a light
automated sanity check (tag balance, no raw "<script>" survives) so it's not
purely eyeball-only.

Usage:
    python3 scripts/test_markdown_to_html.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram_format import markdown_to_html

SAMPLES = [
    (
        "Обычный текст с жирным и кодом",
        "Отличный ход! **Зевок ферзя** — надо было сыграть `Ne2`.",
    ),
    (
        "Несколько акцентов и кодовых вставок в одном сообщении",
        "Два **акцента** и **ещё один**, плюс `код1` и `код2`.",
    ),
    (
        "Попытка внедрить <script>",
        "Проверка <script>alert('xss')</script> инъекции.",
    ),
    (
        "Незакрытая двойная звёздочка",
        "Это **незакрытый акцент без второй пары.",
    ),
    (
        "Незакрытая обратная кавычка",
        "Ход `Qxf6 без закрывающей кавычки.",
    ),
    (
        "Литеральные HTML-спецсимволы в обычном тексте (без форматирования)",
        "Оценка < -5, что хуже & больше > нормы.",
    ),
    (
        "Поддельные HTML-теги внутри разметки (вложенная инъекция)",
        "**<b>fake bold</b>** normal text `<i>fake code</i>`",
    ),
    (
        "Пустая строка",
        "",
    ),
    (
        "Реалистичная подпись к ходу партии",
        "**Зевок!** `Qxf6??` отдаёт ферзя даром — лучше было `Ne2`, сохраняя перевес.",
    ),
]

_TAG_OPEN_RE = re.compile(r"<(b|code)>")
_TAG_CLOSE_RE = re.compile(r"</(b|code)>")


def _is_tag_balanced(html_text: str) -> bool:
    return len(_TAG_OPEN_RE.findall(html_text)) == len(_TAG_CLOSE_RE.findall(html_text))


def main() -> None:
    all_ok = True

    for title, sample in SAMPLES:
        result = markdown_to_html(sample)
        print(f"--- {title} ---")
        print(f"INPUT:  {sample!r}")
        print(f"OUTPUT: {result!r}")

        balanced = _is_tag_balanced(result)
        no_live_script = "<script>" not in result
        checks_passed = balanced and no_live_script
        all_ok = all_ok and checks_passed

        print(f"tags balanced: {balanced}, no live <script>: {no_live_script}")
        print()

    print("=" * 60)
    print("ALL SANITY CHECKS PASSED" if all_ok else "SOME SANITY CHECKS FAILED")


if __name__ == "__main__":
    main()
