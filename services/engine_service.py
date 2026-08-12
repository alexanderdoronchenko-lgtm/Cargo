"""Finds notable moments in a game using Stockfish — mistakes (blunders) and
strong moves worth praising — and scores the game's overall accuracy.
"""
import math
from dataclasses import dataclass

import chess
import chess.engine
import chess.pgn

import config

DEFAULT_DEPTH = 18
# Lowered from 1.0s after production timing showed Stockfish analysis
# (one analyse() call per ply, almost always bound by this time limit
# rather than by DEFAULT_DEPTH) accounting for ~73% of a review's total
# latency — 75s of a 103s review on a 12-moment, ~40-move game. 0.4s/ply
# trades some engine strength for a roughly 2.5x speedup on this stage;
# combined with Threads below it should cut it further.
DEFAULT_TIME_LIMIT = 0.4
DEFAULT_CP_LOSS_THRESHOLD = 100

# A played move that matches the engine's top choice counts as a "strength"
# moment when the position was genuinely hard to solve — i.e. the engine's
# second-best try was meaningfully worse than its best one (found via
# MULTIPV below).
DEFAULT_STRENGTH_GAP_THRESHOLD = 150

# A non-capturing move counts as a "strength" moment when it swings the
# evaluation in the mover's favor by at least this much. Captures are
# excluded so an easy free-material grab (the opponent's mistake, not this
# player's skill) doesn't get flagged as impressive.
DEFAULT_STRENGTH_GAIN_THRESHOLD = 150

TYPE_MISTAKE = "mistake"
TYPE_STRENGTH = "strength"

# Best + second-best line, needed to detect "only good move" strength
# moments (the gap between them).
_MULTIPV = 2

# How many plies of surrounding move context to keep for each moment,
# instead of the full game notation.
CONTEXT_PLIES = 2

# A game with a lot of inaccuracies (or brilliancies) shouldn't turn into a
# move-by-move log — cap it to the most notable mistakes and strong moves
# together, matching the corpus's natural density (roughly 6-12 comments
# per game).
MAX_CRITICAL_MOMENTS = 12

_MATE_SCORE = 100_000

# Cap on how much a single move counts toward the game's average centipawn
# loss (ACPL) — without it, one blunder into a mating line (loss in the
# tens of thousands of "cp") would swamp the average and floor the whole
# game's accuracy regardless of every other move, which isn't a useful
# signal. 1000 is a commonly used cap in open ACPL implementations.
_ACCURACY_LOSS_CAP_CP = 1000


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
    type: str = TYPE_MISTAKE  # TYPE_MISTAKE or TYPE_STRENGTH
    # How notable this moment is, on one scale comparable across both types
    # (cp_loss for mistakes, the engine-gap or favorable swing for
    # strengths) — used by select_top_moments to rank/cap them together.
    magnitude: int = 0


@dataclass
class GameAnalysis:
    moments: list[CriticalMoment]
    # Whole-game accuracy percentage (0-100), derived from average
    # centipawn loss across every ply — see _accuracy_percent.
    accuracy_pct: float


def _accuracy_percent(average_cp_loss: float) -> float:
    """Maps average centipawn loss (ACPL) to an accuracy percentage with an
    exponential decay curve, in the spirit of chess.com/Lichess-style
    accuracy scores (the task explicitly allows "any reasonable open
    formula" rather than reimplementing an official one). Calibrated so
    ACPL 0 -> 100%, ACPL ~10 -> ~96% (strong play), ACPL ~50 -> ~80%
    (solid club play), ACPL ~100 -> ~64% (error-prone), clamped to
    [0, 100].
    """
    accuracy = 103.1668 * math.exp(-0.004354 * average_cp_loss) - 3.1669
    return max(0.0, min(100.0, accuracy))


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
    """Keeps at most `max_count` moments — mistakes and strengths ranked
    together by how notable each one is (`magnitude`) — while preserving
    chronological order.
    """
    if len(moments) <= max_count:
        return moments
    keep_keys = {
        (m.move_number, m.side)
        for m in sorted(moments, key=lambda m: m.magnitude, reverse=True)[:max_count]
    }
    return [m for m in moments if (m.move_number, m.side) in keep_keys]


async def analyze_game(
    game: chess.pgn.Game,
    depth: int = DEFAULT_DEPTH,
    time_limit: float = DEFAULT_TIME_LIMIT,
    cp_loss_threshold: int = DEFAULT_CP_LOSS_THRESHOLD,
    strength_gap_threshold: int = DEFAULT_STRENGTH_GAP_THRESHOLD,
    strength_gain_threshold: int = DEFAULT_STRENGTH_GAIN_THRESHOLD,
    user_side: str | None = None,
) -> GameAnalysis:
    """If `user_side` ("white"/"black") is given, the returned accuracy_pct
    is computed from that side's plies only — it's presented to the user as
    *their* accuracy, so it shouldn't be diluted by the opponent's moves.
    Left as None, it falls back to whole-game accuracy across both sides.
    """
    if not config.STOCKFISH_PATH:
        raise EngineError("STOCKFISH_PATH is not configured. Add it to your .env file.")

    plies = _build_ply_list(game)

    try:
        _, engine = await chess.engine.popen_uci(config.STOCKFISH_PATH)
    except OSError as exc:
        raise EngineError(f"Failed to start Stockfish at {config.STOCKFISH_PATH!r}: {exc}") from exc

    limit = chess.engine.Limit(depth=depth, time=time_limit)
    critical_moments: list[CriticalMoment] = []
    total_capped_loss = 0
    ply_count = 0

    try:
        board = game.board()
        # Multi-threaded search per position — set once at startup, applies
        # to every analyse() call below. Independent of, and stacks with,
        # the time_limit reduction above.
        await engine.configure({"Threads": config.STOCKFISH_THREADS})
        # multipv=2 so the "only good move" strength check below can compare
        # the engine's best try against its second-best one. This one call
        # per position is reused as both the "after" evaluation of the
        # previous ply and the "before" evaluation of the next one.
        lines = await engine.analyse(board, limit, multipv=_MULTIPV)

        for ply_index, node in enumerate(game.mainline()):
            move = node.move
            mover = board.turn
            move_number = board.fullmove_number
            move_san = board.san(move)
            is_capture = board.is_capture(move)

            best_move = lines[0].get("pv", [None])[0]
            best_move_san = board.san(best_move) if best_move else None
            best_move_uci = best_move.uci() if best_move else None
            score_before = _score_cp(lines[0]["score"], mover)
            second_best_cp = _score_cp(lines[1]["score"], mover) if len(lines) > 1 else None
            engine_gap = score_before - second_best_cp if second_best_cp is not None else None

            board.push(move)
            lines = await engine.analyse(board, limit, multipv=_MULTIPV)
            score_after = _score_cp(lines[0]["score"], mover)

            cp_loss = score_before - score_after
            mover_side = "white" if mover == chess.WHITE else "black"
            if user_side is None or mover_side == user_side:
                total_capped_loss += max(0, min(cp_loss, _ACCURACY_LOSS_CAP_CP))
                ply_count += 1

            moment_type = None
            magnitude = 0
            if cp_loss > cp_loss_threshold:
                moment_type = TYPE_MISTAKE
                magnitude = cp_loss
            elif move == best_move and engine_gap is not None and engine_gap >= strength_gap_threshold:
                # The played move was the engine's top choice, and missing
                # it would have cost a lot — a hard-to-find "only good move".
                moment_type = TYPE_STRENGTH
                magnitude = engine_gap
            elif not is_capture and cp_loss <= -strength_gain_threshold:
                # A quiet (non-capturing) move that swung the evaluation
                # noticeably in the mover's favor.
                moment_type = TYPE_STRENGTH
                magnitude = -cp_loss

            if moment_type is not None:
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
                        type=moment_type,
                        magnitude=magnitude,
                    )
                )
    finally:
        await engine.quit()

    acpl = total_capped_loss / ply_count if ply_count else 0.0
    return GameAnalysis(moments=critical_moments, accuracy_pct=_accuracy_percent(acpl))
