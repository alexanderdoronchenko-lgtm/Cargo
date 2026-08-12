"""Mini App backend — a separate FastAPI process from the aiogram bot, but
sharing the same SQLite database (via database.py) and hence the same
users/subscriptions/puzzles tables.

Run with: uvicorn api.main:app --reload --port 8000
"""
import json
import random
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
import chess
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
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

# Streak freeze — Diamond-only.
_STREAK_FREEZE_TIERS = {"diamond"}

# Opening trainer — Emerald/Diamond only.
_OPENING_TRAINER_TIERS = {"emerald", "diamond"}
_OPENINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "openings.json"
_openings_cache: dict | None = None


def _load_openings() -> dict:
    global _openings_cache
    if _openings_cache is None:
        with open(_OPENINGS_PATH, encoding="utf-8") as f:
            _openings_cache = json.load(f)
    return _openings_cache


# Background-music player: lists whatever's actually in miniapp/public/audio
# at request time (not a hardcoded filename), so dropping a new track in
# there is all it takes for the player to pick it up — no code change, no
# restart. Playback itself is served by whatever's hosting the Mini App's
# static files (Vite's public/ dir), not by this API — this endpoint only
# answers "what's in the folder right now".
_AUDIO_DIR = Path(__file__).resolve().parent.parent / "miniapp" / "public" / "audio"
_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".ogg", ".wav"}


async def _get_tier(user_id: int) -> str:
    """Live check against subscriptions, same as everywhere else tier
    gates a feature — users.subscription_tier is a cache that can lag up
    to 24h behind an actual expiry.

    The configured admin is treated as Diamond regardless of any real
    subscription. Diamond already unlocks every tier-gated feature this
    function feeds (targeted puzzle selection, the streak freeze, the
    opening trainer), so this one mapping covers all of them at once
    rather than needing a separate bypass at each call site.
    """
    if config.ADMIN_USER_ID is not None and user_id == config.ADMIN_USER_ID:
        return "diamond"
    active = await database.get_active_subscription(user_id)
    return active["tier"] if active is not None else "free"


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
    allow_methods=["GET", "POST"],
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
        tier = await _get_tier(user_id)
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


class PuzzleStatsResponse(BaseModel):
    solved_today: int
    streak_days: int
    # Diamond and a freeze hasn't been used in the last 30 days — shown as
    # the 🛡️ hint so the user knows a missed day won't cost them right now.
    freeze_available: bool
    # True only on the specific /puzzle/solved call whose streak update
    # actually bridged a missed day with a freeze.
    freeze_applied: bool = False


@app.get("/api/puzzle/stats", response_model=PuzzleStatsResponse)
async def puzzle_stats(user_id: int = Query(...)):
    tier = await _get_tier(user_id)
    row = await database.get_latest_puzzle_stats(user_id)

    today = database.today_str()
    solved_today = row["solved_count"] if row is not None and row["date"] == today else 0
    streak_days = row["streak_days"] if row is not None else 0
    freeze_used_at = row["streak_freeze_used_at"] if row is not None else None

    return PuzzleStatsResponse(
        solved_today=solved_today,
        streak_days=streak_days,
        freeze_available=tier in _STREAK_FREEZE_TIERS and database.is_streak_freeze_available(freeze_used_at),
    )


@app.post("/api/puzzle/solved", response_model=PuzzleStatsResponse)
async def puzzle_solved(user_id: int = Query(...)):
    tier = await _get_tier(user_id)
    freeze_eligible = tier in _STREAK_FREEZE_TIERS

    row, freeze_applied = await database.record_puzzle_solved(user_id, freeze_eligible)

    return PuzzleStatsResponse(
        solved_today=row["solved_count"],
        streak_days=row["streak_days"],
        freeze_available=freeze_eligible and database.is_streak_freeze_available(row["streak_freeze_used_at"]),
        freeze_applied=freeze_applied,
    )


@app.get("/api/openings")
async def openings(user_id: int = Query(...)):
    """Emerald/Diamond only, enforced here rather than just hidden in the
    UI — an ineligible request never gets the repertoire content itself,
    not just a locked-looking screen.
    """
    tier = await _get_tier(user_id)
    if tier not in _OPENING_TRAINER_TIERS:
        raise HTTPException(403, "Opening trainer requires Emerald tier or higher")

    return _load_openings()


class UserInfoResponse(BaseModel):
    language: str


@app.get("/api/user", response_model=UserInfoResponse)
async def user_info(
    user_id: int = Query(...),
    username: str | None = Query(None),
    language_code: str | None = Query(None),
):
    """Same resolution the bot itself uses: an existing row's stored
    language (set via /language) wins over whatever language_code the
    Telegram client reports today; a first-time user gets one resolved
    from language_code and persisted. get_or_create_user is the exact
    function the bot's handlers call, so the two surfaces can never
    disagree on a given user's language.
    """
    language = await database.get_or_create_user(user_id, username, language_code)
    return UserInfoResponse(language=language)


@app.get("/api/audio/tracks")
async def audio_tracks():
    if not _AUDIO_DIR.is_dir():
        return {"tracks": []}
    tracks = sorted(
        p.name for p in _AUDIO_DIR.iterdir() if p.is_file() and p.suffix.lower() in _AUDIO_EXTENSIONS
    )
    return {"tracks": tracks}
