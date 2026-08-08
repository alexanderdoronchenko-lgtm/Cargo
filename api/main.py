"""Mini App backend — a separate FastAPI process from the aiogram bot, but
sharing the same SQLite database (via database.py) and hence the same
users/subscriptions/puzzles tables.

Run with: uvicorn api.main:app --reload --port 8000
"""
from contextlib import asynccontextmanager

import chess
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import database

_MIN_RATING = 0
_MAX_RATING = 3000


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.init_db()
    yield


app = FastAPI(title="Critical Moment Mini App API", lifespan=lifespan)

# Puzzle data is public and read-only — no user data crosses this endpoint —
# so an open CORS policy is fine; the Mini App is served from whatever host
# Telegram's WebView loads it from, which isn't known/fixed ahead of time.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


class PuzzleResponse(BaseModel):
    puzzle_id: str
    fen: str
    solution: list[str]
    rating: int
    side_to_move: str
    themes: list[str]


@app.get("/api/puzzle/random", response_model=PuzzleResponse)
async def random_puzzle(
    rating_min: int = Query(400, ge=_MIN_RATING, le=_MAX_RATING),
    rating_max: int = Query(2000, ge=_MIN_RATING, le=_MAX_RATING),
):
    if rating_min > rating_max:
        raise HTTPException(400, "rating_min must be <= rating_max")

    row = await database.get_random_puzzle(rating_min, rating_max)
    if row is None:
        raise HTTPException(404, "No puzzles available")

    board = chess.Board(row["fen"])
    return PuzzleResponse(
        puzzle_id=row["puzzle_id"],
        fen=row["fen"],
        solution=row["solution"].split(),
        rating=row["rating"],
        side_to_move="white" if board.turn == chess.WHITE else "black",
        themes=row["themes"].split() if row["themes"] else [],
    )
