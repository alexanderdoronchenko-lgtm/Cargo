"""One-off import of the curated Lichess puzzle sample into SQLite.

Source: data/lichess_puzzles_sample.csv — a stratified-by-rating sample of
real Lichess puzzles (columns: PuzzleId, FEN, Moves, Rating, RatingDeviation,
Popularity, NbPlays, Themes, GameUrl). See that file's own provenance note
for where it came from and why.

Lichess's own FEN/Moves convention: FEN is the position *before* the puzzle
starts, and the first move in Moves is the move that was actually played in
the source game (not something the solver plays) — it's what turns the
position into the puzzle. This script applies that move up front and stores
the resulting position as `fen`, so the API can hand the frontend a position
that's immediately playable: `solution` is exactly the moves the solver
needs to find (alternating with the opponent's forced replies).

Usage: python scripts/import_puzzles.py
"""
import asyncio
import csv
import sys
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "lichess_puzzles_sample.csv"
BATCH_SIZE = 500


def _build_row(csv_row: dict) -> tuple | None:
    moves = csv_row["Moves"].split()
    if len(moves) < 2:
        return None  # nothing left for the solver to actually find

    board = chess.Board(csv_row["FEN"])
    board.push(chess.Move.from_uci(moves[0]))

    return (
        csv_row["PuzzleId"],
        board.fen(),
        " ".join(moves[1:]),
        int(csv_row["Rating"]),
        int(csv_row["RatingDeviation"]) if csv_row["RatingDeviation"] else None,
        int(csv_row["Popularity"]) if csv_row["Popularity"] else None,
        csv_row["Themes"],
    )


async def main() -> None:
    if not CSV_PATH.exists():
        raise SystemExit(f"{CSV_PATH} not found")

    await database.init_db()

    batch: list[tuple] = []
    total_read = 0
    total_inserted = 0
    skipped = 0

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for csv_row in csv.DictReader(f):
            total_read += 1
            row = _build_row(csv_row)
            if row is None:
                skipped += 1
                continue
            batch.append(row)
            if len(batch) >= BATCH_SIZE:
                total_inserted += await database.bulk_insert_puzzles(batch)
                batch.clear()

    if batch:
        total_inserted += await database.bulk_insert_puzzles(batch)

    total_in_db = await database.count_puzzles()
    print(
        f"Read {total_read} rows, skipped {skipped}, inserted {total_inserted} new "
        f"puzzles. Table now has {total_in_db} rows total."
    )


if __name__ == "__main__":
    asyncio.run(main())
