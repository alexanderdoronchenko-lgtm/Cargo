"""Finds critical moments (blunders/mistakes) in a game using Stockfish."""
from dataclasses import dataclass

import chess
import chess.engine
import chess.pgn

import config

DEFAULT_DEPTH = 18
DEFAULT_TIME_LIMIT = 1.0
DEFAULT_CP_LOSS_THRESHOLD = 100

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


def _score_cp(score: chess.engine.PovScore, color: chess.Color) -> int:
    return score.pov(color).score(mate_score=_MATE_SCORE)


async def analyze_game(
    game: chess.pgn.Game,
    depth: int = DEFAULT_DEPTH,
    time_limit: float = DEFAULT_TIME_LIMIT,
    cp_loss_threshold: int = DEFAULT_CP_LOSS_THRESHOLD,
) -> list[CriticalMoment]:
    if not config.STOCKFISH_PATH:
        raise EngineError("STOCKFISH_PATH is not configured. Add it to your .env file.")

    try:
        _, engine = await chess.engine.popen_uci(config.STOCKFISH_PATH)
    except OSError as exc:
        raise EngineError(f"Failed to start Stockfish at {config.STOCKFISH_PATH!r}: {exc}") from exc

    limit = chess.engine.Limit(depth=depth, time=time_limit)
    critical_moments: list[CriticalMoment] = []

    try:
        board = game.board()
        info = await engine.analyse(board, limit)

        for node in game.mainline():
            move = node.move
            mover = board.turn
            move_number = board.fullmove_number
            move_san = board.san(move)

            best_move = info.get("pv", [None])[0]
            best_move_san = board.san(best_move) if best_move else None
            score_before = _score_cp(info["score"], mover)

            board.push(move)
            info = await engine.analyse(board, limit)
            score_after = _score_cp(info["score"], mover)

            cp_loss = score_before - score_after
            if cp_loss > cp_loss_threshold:
                critical_moments.append(
                    CriticalMoment(
                        move_number=move_number,
                        side="white" if mover == chess.WHITE else "black",
                        move_san=move_san,
                        best_move_san=best_move_san,
                        score_before_cp=score_before,
                        score_after_cp=score_after,
                        cp_loss=cp_loss,
                    )
                )
    finally:
        await engine.quit()

    return critical_moments
