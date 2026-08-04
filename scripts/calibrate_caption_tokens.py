"""Recalibrates commentary_service's per-explanation token budget against the
real Claude tokenizer (never approximate Claude token counts with tiktoken —
it's a different tokenizer and undercounts, especially on Cyrillic text).

Extracts each per-move annotation from chess_style_corpus.md, counts its
tokens via the Messages API's count_tokens endpoint, and prints the average
with a 20% headroom margin plus the recommended max_tokens for a
MAX_CRITICAL_MOMENTS-sized batch. Update the constants in
services/commentary_service.py with the printed numbers.

Usage:
    ANTHROPIC_API_KEY=sk-ant-... python3 scripts/calibrate_caption_tokens.py
"""
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic

import config
from services.engine_service import MAX_CRITICAL_MOMENTS

_MOVE_LINE_RE = re.compile(
    r"^\s*(?:\d+\.(?:\.\.\.)?\s*)?"
    r"(?:[!?]{1,2})?"
    r"(?:O-O-O|O-O|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?)"
    r"[!?]{0,2}\s*(.*)$"
)


def extract_annotations(corpus_text: str) -> list[str]:
    annotations = []
    for line in corpus_text.splitlines():
        match = _MOVE_LINE_RE.match(line)
        if not match:
            continue
        text = match.group(1).strip()
        if text:
            annotations.append(text)
    return annotations


def main() -> None:
    corpus_path = config.BASE_DIR / "chess_style_corpus.md"
    annotations = extract_annotations(corpus_path.read_text(encoding="utf-8"))
    if not annotations:
        raise SystemExit(f"No per-move annotations found in {corpus_path}")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    token_counts = [
        client.messages.count_tokens(
            model=config.CLAUDE_MODEL,
            messages=[{"role": "user", "content": text}],
        ).input_tokens
        for text in annotations
    ]

    average = statistics.mean(token_counts)
    with_headroom = round(average * 1.2)

    print(f"Annotations sampled: {len(annotations)}")
    print(f"Average tokens/annotation: {average:.1f}")
    print(f"Max tokens/annotation seen: {max(token_counts)}")
    print(f"With 20% headroom: {with_headroom}")
    print()
    print("Update in services/commentary_service.py:")
    print(f"  _AVG_EXPLANATION_TOKENS_WITH_HEADROOM = {with_headroom}")
    print(f"  (MAX_CRITICAL_MOMENTS = {MAX_CRITICAL_MOMENTS})")


if __name__ == "__main__":
    main()
