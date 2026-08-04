"""Parses PGN games and recognizes links to chess.com / lichess.org."""
import io
import re
from urllib.parse import urlparse

import chess.pgn

_URL_RE = re.compile(r"https?://\S+")
_PGN_TAG_RE = re.compile(r'^\s*\[\w+\s+".*"\]\s*$', re.MULTILINE)
_MOVE_NUMBER_RE = re.compile(r"\b\d+\.")

_PLATFORM_HOSTS = {
    "chess.com": "chess.com",
    "lichess.org": "lichess.org",
}


def extract_url(text: str) -> str | None:
    match = _URL_RE.search(text)
    return match.group(0) if match else None


def detect_platform(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    for needle, platform in _PLATFORM_HOSTS.items():
        if needle in host:
            return platform
    return None


async def fetch_game_by_url(url: str, platform: str) -> str | None:
    """TODO: download the game's PGN from the platform's API.

    chess.com: https://api.chess.com/pub/...
    lichess.org: https://lichess.org/game/export/{id}.pgn

    Not implemented yet — wired up in a follow-up step.
    """
    raise NotImplementedError


def _looks_like_pgn(text: str) -> bool:
    return bool(_PGN_TAG_RE.search(text) or _MOVE_NUMBER_RE.search(text))


def parse_pgn(text: str) -> chess.pgn.Game | None:
    if not _looks_like_pgn(text):
        return None
    game = chess.pgn.read_game(io.StringIO(text))
    if game is None or game.errors:
        return None
    return game


def count_moves(game: chess.pgn.Game) -> int:
    return sum(1 for _ in game.mainline_moves())
