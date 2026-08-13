"""Parses PGN games, recognizes chess.com / lichess.org links, and downloads
the game they point to.
"""
import asyncio
import io
import re
from datetime import datetime, timedelta, timezone
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


def _month_start(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _find_chesscom_pgn_in_archive(username: str, game_id: str) -> str | None:
    """Fallback for when the unofficial callback endpoint above fails
    (private-looking response, TCN-only data, or it 404s/times out) but
    the user has a chess.com username linked via /chesscom: searches
    their official public archive (api.chess.com/pub/player/.../games/
    {year}/{month} — the one endpoint chess.com's PubAPI actually
    documents) for the same game and returns its real PGN.

    The archive has no "fetch by id" endpoint either, only whole months,
    so this downloads a month at a time (current, then previous, stopping
    at the first match) and matches each archived game's own `url` field
    against `game_id` — that field is chess.com's own link to the game, in
    the same /game/(live|daily)/<id> shape as what users share, so this is
    an exact id match, not a fuzzy time/participant heuristic. Returns
    None (never raises) if nothing matches or the archive itself is
    unreachable — this is a secondary path, not the primary one.
    """
    now = datetime.now(timezone.utc)
    current_month = _month_start(now)
    previous_month = _month_start(current_month - timedelta(days=1))

    async with aiohttp.ClientSession() as session:
        for month_start in (current_month, previous_month):
            archive_url = (
                f"https://api.chess.com/pub/player/{username}/games/"
                f"{month_start.year:04d}/{month_start.month:02d}"
            )
            try:
                async with session.get(
                    archive_url,
                    headers={"User-Agent": _USER_AGENT},
                    timeout=_REQUEST_TIMEOUT,
                ) as response:
                    if response.status != 200:
                        continue
                    data = await response.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError):
                continue

            games = data.get("games") if isinstance(data, dict) else None
            if not isinstance(games, list):
                continue

            for game in games:
                if not isinstance(game, dict):
                    continue
                game_url_match = _CHESSCOM_GAME_RE.search(game.get("url") or "")
                if game_url_match and game_url_match.group(2) == game_id:
                    pgn = game.get("pgn")
                    if pgn:
                        return pgn

    return None


async def fetch_game_by_url(url: str, platform: str, chesscom_username: str | None = None) -> str:
    if platform == "lichess.org":
        match = _LICHESS_GAME_ID_RE.search(url)
        if not match:
            raise InvalidLinkError()
        return await _fetch_lichess_pgn(match.group(1))

    if platform == "chess.com":
        match = _CHESSCOM_GAME_RE.search(url)
        if not match:
            raise InvalidLinkError()
        game_type, game_id = match.group(1), match.group(2)
        try:
            return await _fetch_chesscom_pgn(game_type, game_id)
        except GameFetchError:
            if chesscom_username:
                pgn = await _find_chesscom_pgn_in_archive(chesscom_username, game_id)
                if pgn:
                    return pgn
            # Re-raise the original failure (not_found/private/unsupported/
            # network) rather than a generic one — it's still the more
            # informative reason, the archive lookup was just a second
            # chance at getting the PGN despite it.
            raise

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
