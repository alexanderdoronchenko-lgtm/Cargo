"""Parses PGN games, recognizes chess.com / lichess.org links, and downloads
the game they point to.
"""
import asyncio
import io
import re
from urllib.parse import urlparse

import aiohttp
import chess.pgn

_URL_RE = re.compile(r"https?://\S+")
_PGN_TAG_RE = re.compile(r'^\s*\[\w+\s+".*"\]\s*$', re.MULTILINE)
_MOVE_NUMBER_RE = re.compile(r"\b\d+\.")

_PLATFORM_HOSTS = {
    "chess.com": "chess.com",
    "lichess.org": "lichess.org",
}

_LICHESS_GAME_ID_RE = re.compile(r"lichess\.org/(?:embed/)?([A-Za-z0-9]{8})")
_CHESSCOM_GAME_RE = re.compile(r"chess\.com/(?:[\w-]+/)*game/(live|daily)/(\d+)")

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
_USER_AGENT = "Mozilla/5.0 (compatible; ChessAnalysisBot/1.0)"


class GameFetchError(Exception):
    """Raised when a game can't be downloaded. `reason` names why, and maps
    to a `game_fetch_error_{reason}` locale key.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class InvalidLinkError(GameFetchError):
    def __init__(self):
        super().__init__("invalid_link")


class GameNotFoundError(GameFetchError):
    def __init__(self):
        super().__init__("not_found")


class GamePrivateError(GameFetchError):
    def __init__(self):
        super().__init__("private")


class GameUnsupportedError(GameFetchError):
    def __init__(self):
        super().__init__("unsupported")


def extract_url(text: str) -> str | None:
    match = _URL_RE.search(text)
    return match.group(0) if match else None


def detect_platform(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    for needle, platform in _PLATFORM_HOSTS.items():
        if needle in host:
            return platform
    return None


async def _fetch_lichess_pgn(game_id: str) -> str:
    url = f"https://lichess.org/game/export/{game_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"Accept": "application/x-chess-pgn"},
                timeout=_REQUEST_TIMEOUT,
            ) as response:
                if response.status == 404:
                    raise GameNotFoundError()
                if response.status in (401, 403):
                    raise GamePrivateError()
                if response.status != 200:
                    raise GameFetchError("network")
                pgn = await response.text()
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise GameFetchError("network") from exc

    if not pgn.strip():
        raise GameNotFoundError()
    return pgn


async def _fetch_chesscom_pgn(game_type: str, game_id: str) -> str:
    # chess.com's official public API (api.chess.com/pub/...) has no endpoint
    # to fetch a single game by id — only a player's monthly archive, which
    # needs a username we don't have from a bare game link. This callback
    # endpoint is what chess.com's own web client calls to render a game
    # page. It's undocumented/unofficial: the response shape isn't
    # guaranteed and the endpoint may change or disappear without notice.
    url = f"https://www.chess.com/callback/{game_type}/game/{game_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=_REQUEST_TIMEOUT,
            ) as response:
                if response.status == 404:
                    raise GameNotFoundError()
                if response.status in (401, 403):
                    raise GamePrivateError()
                if response.status != 200:
                    raise GameFetchError("network")
                data = await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise GameFetchError("network") from exc

    game_data = data.get("game") if isinstance(data, dict) else None
    if not isinstance(game_data, dict):
        raise GameNotFoundError()

    pgn = game_data.get("pgn") or (data.get("pgn") if isinstance(data, dict) else None)
    if not pgn:
        # The endpoint returned game data but no ready-made PGN text (e.g.
        # only an encoded moveList) — decoding chess.com's proprietary move
        # encoding isn't supported here.
        raise GameUnsupportedError()

    return pgn


async def fetch_game_by_url(url: str, platform: str) -> str:
    if platform == "lichess.org":
        match = _LICHESS_GAME_ID_RE.search(url)
        if not match:
            raise InvalidLinkError()
        return await _fetch_lichess_pgn(match.group(1))

    if platform == "chess.com":
        match = _CHESSCOM_GAME_RE.search(url)
        if not match:
            raise InvalidLinkError()
        return await _fetch_chesscom_pgn(match.group(1), match.group(2))

    raise InvalidLinkError()


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
