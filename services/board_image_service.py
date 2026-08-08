"""Renders a chess position as a PNG, with the last move marked by an arrow
and a highlighted destination square. When the engine's preferred move
differs from the move actually played, a second, smaller arrow shows what
should have been played instead.
"""
import math

import cairosvg
import chess
import chess.svg

_BOARD_SIZE = 400
# Terracotta — matches --color-accent-terracotta in miniapp/theme.css.
_ARROW_COLOR = "#C1502Ecc"
_FILL_COLOR = "#C1502Eaa"
_BEST_MOVE_ARROW_COLOR = "#3FA66Ccc"
_BEST_MOVE_ARROW_SCALE = 0.7

# chess.svg draws arrows in its own fixed internal coordinate space
# (SQUARE_SIZE=45), at board_offset=15 for the coordinates=True/borders=False
# default we render with below. Its public `arrows=` parameter always draws
# every arrow at the same size, so the second (engine) arrow is added by
# hand here, replicating that same geometry with a smaller scale factor.
_SQUARE_SIZE = chess.svg.SQUARE_SIZE
_BOARD_OFFSET = 15


def _arrow_fragment(tail: chess.Square, head: chess.Square, color: str, scale: float) -> str:
    tail_file, tail_rank = chess.square_file(tail), chess.square_rank(tail)
    head_file, head_rank = chess.square_file(head), chess.square_rank(head)

    xtail = _BOARD_OFFSET + (tail_file + 0.5) * _SQUARE_SIZE
    ytail = _BOARD_OFFSET + (7.5 - tail_rank) * _SQUARE_SIZE
    xhead = _BOARD_OFFSET + (head_file + 0.5) * _SQUARE_SIZE
    yhead = _BOARD_OFFSET + (7.5 - head_rank) * _SQUARE_SIZE

    marker_size = 0.75 * _SQUARE_SIZE * scale
    marker_margin = 0.1 * _SQUARE_SIZE * scale

    dx, dy = xhead - xtail, yhead - ytail
    hypot = math.hypot(dx, dy)

    shaft_x = xhead - dx * (marker_size + marker_margin) / hypot
    shaft_y = yhead - dy * (marker_size + marker_margin) / hypot
    xtip = xhead - dx * marker_margin / hypot
    ytip = yhead - dy * marker_margin / hypot

    marker = [
        (xtip, ytip),
        (shaft_x + dy * 0.5 * marker_size / hypot, shaft_y - dx * 0.5 * marker_size / hypot),
        (shaft_x - dy * 0.5 * marker_size / hypot, shaft_y + dx * 0.5 * marker_size / hypot),
    ]
    points = " ".join(f"{x:.2f},{y:.2f}" for x, y in marker)

    return (
        f'<line x1="{xtail:.2f}" y1="{ytail:.2f}" x2="{shaft_x:.2f}" y2="{shaft_y:.2f}" '
        f'stroke="{color}" stroke-width="{_SQUARE_SIZE * 0.2 * scale:.2f}" stroke-linecap="butt"/>'
        f'<polygon points="{points}" fill="{color}"/>'
    )


def render_position_png(fen_after: str, move_uci: str, best_move_uci: str | None = None) -> bytes:
    board = chess.Board(fen_after)
    move = chess.Move.from_uci(move_uci)

    svg_data = chess.svg.board(
        board=board,
        arrows=[chess.svg.Arrow(move.from_square, move.to_square, color=_ARROW_COLOR)],
        fill={move.to_square: _FILL_COLOR},
        size=_BOARD_SIZE,
    )

    if best_move_uci and best_move_uci != move_uci:
        best_move = chess.Move.from_uci(best_move_uci)
        best_arrow_svg = _arrow_fragment(
            best_move.from_square, best_move.to_square, _BEST_MOVE_ARROW_COLOR, _BEST_MOVE_ARROW_SCALE
        )
        svg_data = svg_data.replace("</svg>", best_arrow_svg + "</svg>")

    return cairosvg.svg2png(bytestring=svg_data.encode("utf-8"))
