"""Mini App backend — a separate FastAPI process from the aiogram bot, but
sharing the same SQLite database (via database.py) and hence the same
users/subscriptions/puzzles tables.

Run with: uvicorn api.main:app --reload --port 8000
"""
import random
from contextlib import asynccontextmanager

import aiosqlite
import chess
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import database
from services import puzzle_category_service
from services.usage_service import ACTION_CRITICAL_MOMENT

_MIN_RATING = 0
_MAX_RATING = 3000

# Targeted-by-weakness puzzle selection is a paid feature (see the task this
# was built for) — only these tiers get their /progress data read at all.
_TARGETED_SELECTION_TIERS = {"emerald", "diamond"}
_TARGETED_SELECTION_PROBABILITY = 0.6
_WEAKNESS_WINDOW_DAYS = 30


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
    # Set when this puzzle was deliberately picked from one of the user's
    # weak categories (see CATEGORY_LABELS_RU in puzzle_category_service).
    targeted_category: str | None = None
    # Whether targeted selection is available to this user at all (their
    # tier qualifies) — independent of whether *this* puzzle ended up
    # targeted, since that's also gated by the 60% roll and by having any
    # weakness data yet. The frontend uses this to decide whether to show
    # the "upgrade for this" upsell.
    targeted_available: bool = False


async def _pick_targeted_puzzle(
    user_id: int, rating_min: int, rating_max: int
) -> tuple[aiosqlite.Row | None, str | None]:
    moments = await database.get_critical_moments_since(
        user_id, ACTION_CRITICAL_MOMENT, _WEAKNESS_WINDOW_DAYS
    )
    weak_categories = puzzle_category_service.top_weak_categories(moments)
    if not weak_categories or random.random() >= _TARGETED_SELECTION_PROBABILITY:
        return None, None

    category = random.choice(weak_categories)
    tags = puzzle_category_service.category_tags(category)
    row = await database.get_random_puzzle_by_tags(rating_min, rating_max, tags)
    return (row, category) if row is not None else (None, None)


@app.get("/api/puzzle/random", response_model=PuzzleResponse)
async def random_puzzle(
    rating_min: int = Query(400, ge=_MIN_RATING, le=_MAX_RATING),
    rating_max: int = Query(2000, ge=_MIN_RATING, le=_MAX_RATING),
    user_id: int | None = Query(None),
):
    if rating_min > rating_max:
        raise HTTPException(400, "rating_min must be <= rating_max")

    targeted_available = False
    row = None
    targeted_category = None

    if user_id is not None:
        active = await database.get_active_subscription(user_id)
        tier = active["tier"] if active is not None else "free"
        targeted_available = tier in _TARGETED_SELECTION_TIERS
        if targeted_available:
            row, targeted_category = await _pick_targeted_puzzle(user_id, rating_min, rating_max)

    if row is None:
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
        targeted_category=targeted_category,
        targeted_available=targeted_available,
    )
