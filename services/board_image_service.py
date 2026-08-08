"""Renders a chess position as a PNG, with the last move marked by an arrow
and a highlighted destination square.
"""
import cairosvg
import chess
import chess.svg

_BOARD_SIZE = 400
# Terracotta — matches --color-accent-terracotta in miniapp/theme.css.
_ARROW_COLOR = "#C1502Ecc"
_FILL_COLOR = "#C1502Eaa"


def render_position_png(fen_after: str, move_uci: str) -> bytes:
    board = chess.Board(fen_after)
    move = chess.Move.from_uci(move_uci)

    svg_data = chess.svg.board(
        board=board,
        arrows=[chess.svg.Arrow(move.from_square, move.to_square, color=_ARROW_COLOR)],
        fill={move.to_square: _FILL_COLOR},
        size=_BOARD_SIZE,
    )
    return cairosvg.svg2png(bytestring=svg_data.encode("utf-8"))
