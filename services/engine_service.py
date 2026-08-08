"""Finds critical moments (blunders/mistakes) in a game using Stockfish."""
from dataclasses import dataclass

import chess
import chess.engine
import chess.pgn

import config

DEFAULT_DEPTH = 18
DEFAULT_TIME_LIMIT = 1.0
DEFAULT_CP_LOSS_THRESHOLD = 100

# How many plies of surrounding move context to keep for each critical
# moment, instead of the full game notation.
CONTEXT_PLIES = 2

# A game with a lot of inaccuracies shouldn't turn into a move-by-move log —
# cap it to the biggest blunders, matching the corpus's format (opening +
# up to ~10-12 critical moments per game).
MAX_CRITICAL_MOMENTS = 12

_MATE_SCORE = 100_000


class EngineError(Exception):
    """Raised when Stockfish can't be started or queried."""


@dataclass
class CriticalMoment:
    move_number: int
    side: str  # "white" or "black"
    move_san: str
    best_move_san: str | None
    score_before_cp: int
    score_after_cp: int
    cp_loss: int
    move_uci: str  # the played move, for rendering an arrow on the board
    best_move_uci: str | None  # engine's preferred move, for a second arrow
    fen_after: str  # position right after the played move
    context_san: str  # a few plies of SAN notation around the played move


def _score_cp(score: chess.engine.PovScore, color: chess.Color) -> int:
    return score.pov(color).score(mate_score=_MATE_SCORE)


def _build_ply_list(game: chess.pgn.Game) -> list[tuple[int, str, str]]:
    """Returns (move_number, side, san) for every ply, used to build the
    small move-context window around each critical moment.
    """
    plies = []
    board = game.board()
    for node in game.mainline():
        move = node.move
        move_number = board.fullmove_number
        side = "white" if board.turn == chess.WHITE else "black"
        plies.append((move_number, side, board.san(move)))
        board.push(move)
    return plies


def _format_context_window(window: list[tuple[int, str, str]]) -> str:
    parts = []
    for i, (move_number, side, san) in enumerate(window):
        if side == "white":
            parts.append(f"{move_number}.{san}")
        else:
            parts.append(f"{move_number}...{san}" if i == 0 else san)
    return " ".join(parts)


def select_top_moments(
    moments: list[CriticalMoment], max_count: int = MAX_CRITICAL_MOMENTS
) -> list[CriticalMoment]:
    """Keeps at most `max_count` moments — the biggest blunders by cp_loss —
    while preserving chronological order.
    """
    if len(moments) <= max_count:
        return moments
    keep_keys = {
        (m.move_number, m.side)
        for m in sorted(moments, key=lambda m: m.cp_loss, reverse=True)[:max_count]
    }
    return [m for m in moments if (m.move_number, m.side) in keep_keys]


async def analyze_game(
    game: chess.pgn.Game,
    depth: int = DEFAULT_DEPTH,
    time_limit: float = DEFAULT_TIME_LIMIT,
    cp_loss_threshold: int = DEFAULT_CP_LOSS_THRESHOLD,
) -> list[CriticalMoment]:
    if not config.STOCKFISH_PATH:
        raise EngineError("STOCKFISH_PATH is not configured. Add it to your .env file.")

    plies = _build_ply_list(game)

    try:
        _, engine = await chess.engine.popen_uci(config.STOCKFISH_PATH)
    except OSError as exc:
        raise EngineError(f"Failed to start Stockfish at {config.STOCKFISH_PATH!r}: {exc}") from exc

    limit = chess.engine.Limit(depth=depth, time=time_limit)
    critical_moments: list[CriticalMoment] = []

    try:
        board = game.board()
        info = await engine.analyse(board, limit)

        for ply_index, node in enumerate(game.mainline()):
            move = node.move
            mover = board.turn
            move_number = board.fullmove_number
            move_san = board.san(move)

            best_move = info.get("pv", [None])[0]
            best_move_san = board.san(best_move) if best_move else None
            best_move_uci = best_move.uci() if best_move else None
            score_before = _score_cp(info["score"], mover)

            board.push(move)
            info = await engine.analyse(board, limit)
            score_after = _score_cp(info["score"], mover)

            cp_loss = score_before - score_after
            if cp_loss > cp_loss_threshold:
                window = plies[max(0, ply_index - CONTEXT_PLIES) : ply_index + CONTEXT_PLIES + 1]
                critical_moments.append(
                    CriticalMoment(
                        move_number=move_number,
                        side="white" if mover == chess.WHITE else "black",
                        move_san=move_san,
                        best_move_san=best_move_san,
                        score_before_cp=score_before,
                        score_after_cp=score_after,
                        cp_loss=cp_loss,
                        move_uci=move.uci(),
                        best_move_uci=best_move_uci,
                        fen_after=board.fen(),
                        context_san=_format_context_window(window),
                    )
                )
    finally:
        await engine.quit()

    return critical_moments
