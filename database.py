"""SQLite access layer built on aiosqlite."""
import random
from datetime import datetime, timezone

import aiosqlite

import config
from locales import DEFAULT_LANG, resolve_lang

_DEFAULT_TIER = "free"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    language TEXT NOT NULL DEFAULT '{DEFAULT_LANG}',
    subscription_tier TEXT NOT NULL DEFAULT '{_DEFAULT_TIER}',
    chesscom_username TEXT,
    lichess_username TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    request_text TEXT NOT NULL,
    result_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
);

CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    action_type TEXT NOT NULL,
    move_number INTEGER,
    move_san TEXT,
    context_san TEXT,
    cp_loss INTEGER,
    FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
);

CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cached_tokens INTEGER NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    tier TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    pending_tier TEXT,
    FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
);

CREATE TABLE IF NOT EXISTS puzzles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    puzzle_id TEXT UNIQUE NOT NULL,
    fen TEXT NOT NULL,
    solution TEXT NOT NULL,
    rating INTEGER NOT NULL,
    rating_deviation INTEGER,
    popularity INTEGER,
    themes TEXT
);

CREATE INDEX IF NOT EXISTS idx_puzzles_rating ON puzzles (rating);

CREATE TABLE IF NOT EXISTS puzzle_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    solved_count INTEGER NOT NULL DEFAULT 0,
    streak_days INTEGER NOT NULL DEFAULT 0,
    streak_freeze_used_at TEXT,
    UNIQUE (telegram_id, date),
    FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
);
"""


async def _rebuild_table(db, table_name: str, create_sql: str, columns: list[str]) -> None:
    """Rebuilds `table_name` using `create_sql`, preserving data for any of
    `columns` present in the old table. Used where SQLite can't alter a
    CHECK constraint in place.
    """
    old_name = f"{table_name}_old"
    await db.execute(f"ALTER TABLE {table_name} RENAME TO {old_name}")
    await db.execute(create_sql)
    cursor = await db.execute(f"PRAGMA table_info({old_name})")
    old_columns = {row[1] async for row in cursor}
    copy_columns = [c for c in columns if c in old_columns]
    column_list = ", ".join(copy_columns)
    await db.execute(
        f"INSERT INTO {table_name} ({column_list}) SELECT {column_list} FROM {old_name}"
    )
    await db.execute(f"DROP TABLE {old_name}")


async def init_db() -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.executescript(_SCHEMA)

        # Upgrade a users table created before the subscription_tier column
        # existed (previously just a boolean is_premium flag).
        cursor = await db.execute("PRAGMA table_info(users)")
        columns = {row[1] async for row in cursor}
        if "subscription_tier" not in columns:
            await db.execute(
                f"ALTER TABLE users ADD COLUMN subscription_tier TEXT NOT NULL "
                f"DEFAULT '{_DEFAULT_TIER}'"
            )

        # Upgrade a users table created before chess platform usernames were
        # tracked (used to auto-detect which side the user played from PGN
        # [White]/[Black] tags).
        for column in ("chesscom_username", "lichess_username"):
            if column not in columns:
                await db.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")

        # Upgrade a usage table created before per-moment columns existed
        # (previously just telegram_id/timestamp/action_type).
        cursor = await db.execute("PRAGMA table_info(usage)")
        usage_columns = {row[1] async for row in cursor}
        for column, column_type in (
            ("move_number", "INTEGER"),
            ("move_san", "TEXT"),
            ("context_san", "TEXT"),
            ("cp_loss", "INTEGER"),
        ):
            if column not in usage_columns:
                await db.execute(f"ALTER TABLE usage ADD COLUMN {column} {column_type}")

        # Upgrade tables created before the Diamond tier: SQLite can't widen
        # a CHECK constraint in place, so users.subscription_tier and
        # subscriptions.tier (both previously CHECK'd to a fixed tier list)
        # get rebuilt without the constraint — tier validity now lives in
        # application code (see usage_service/subscription_service), so
        # adding a future tier never needs another destructive migration.
        # subscriptions.pending_tier (added for deferred downgrades) is the
        # signal that this migration already ran.
        cursor = await db.execute("PRAGMA table_info(subscriptions)")
        subs_columns = {row[1] async for row in cursor}
        if "pending_tier" not in subs_columns:
            await _rebuild_table(
                db,
                "users",
                f"""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    language TEXT NOT NULL DEFAULT '{DEFAULT_LANG}',
                    subscription_tier TEXT NOT NULL DEFAULT '{_DEFAULT_TIER}',
                    chesscom_username TEXT,
                    lichess_username TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """,
                [
                    "id",
                    "telegram_id",
                    "username",
                    "language",
                    "subscription_tier",
                    "chesscom_username",
                    "lichess_username",
                    "created_at",
                ],
            )
            await _rebuild_table(
                db,
                "subscriptions",
                """
                CREATE TABLE subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    tier TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    pending_tier TEXT,
                    FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
                )
                """,
                ["id", "telegram_id", "tier", "expires_at", "pending_tier"],
            )

        await db.commit()


async def get_or_create_user(
    telegram_id: int, username: str | None, language_code: str | None
) -> str:
    """Returns the user's stored language, creating the row on first contact."""
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT language FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()
        if row is not None:
            await db.execute(
                "UPDATE users SET username = ? WHERE telegram_id = ?",
                (username, telegram_id),
            )
            await db.commit()
            return row["language"]

        language = resolve_lang(language_code)
        await db.execute(
            "INSERT INTO users (telegram_id, username, language) VALUES (?, ?, ?)",
            (telegram_id, username, language),
        )
        await db.commit()
        return language


async def set_user_language(telegram_id: int, language: str) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "UPDATE users SET language = ? WHERE telegram_id = ?",
            (language, telegram_id),
        )
        await db.commit()


async def get_user_tier(telegram_id: int) -> str:
    async with aiosqlite.connect(config.DB_PATH) as db:
        cursor = await db.execute(
            "SELECT subscription_tier FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row is not None else _DEFAULT_TIER


async def set_user_tier(telegram_id: int, tier: str) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "UPDATE users SET subscription_tier = ? WHERE telegram_id = ?",
            (tier, telegram_id),
        )
        await db.commit()


async def get_chess_usernames(telegram_id: int) -> tuple[str | None, str | None]:
    """Returns (chesscom_username, lichess_username), used to auto-detect
    which side the user played from a PGN's [White]/[Black] tags.
    """
    async with aiosqlite.connect(config.DB_PATH) as db:
        cursor = await db.execute(
            "SELECT chesscom_username, lichess_username FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        row = await cursor.fetchone()
        return (row[0], row[1]) if row is not None else (None, None)


async def set_chesscom_username(telegram_id: int, username: str) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "UPDATE users SET chesscom_username = ? WHERE telegram_id = ?",
            (username, telegram_id),
        )
        await db.commit()


async def set_lichess_username(telegram_id: int, username: str) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "UPDATE users SET lichess_username = ? WHERE telegram_id = ?",
            (username, telegram_id),
        )
        await db.commit()


async def get_active_subscription(telegram_id: int) -> aiosqlite.Row | None:
    """Live check against expires_at — unlike users.subscription_tier, this
    can't be stale between daily expiry-job runs.
    """
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT tier, expires_at FROM subscriptions
            WHERE telegram_id = ? AND expires_at > datetime('now')
            """,
            (telegram_id,),
        )
        return await cursor.fetchone()


async def upsert_subscription(telegram_id: int, tier: str, expires_at: str) -> None:
    """Activates, renews, or upgrades a subscription — one active period per
    user, never two in parallel. Also cancels any previously queued
    downgrade, since the tier is changing effective immediately.
    """
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO subscriptions (telegram_id, tier, expires_at, pending_tier)
            VALUES (?, ?, ?, NULL)
            ON CONFLICT(telegram_id) DO UPDATE SET
                tier = excluded.tier,
                expires_at = excluded.expires_at,
                pending_tier = NULL
            """,
            (telegram_id, tier, expires_at),
        )
        await db.commit()


async def queue_downgrade(telegram_id: int, pending_tier: str) -> None:
    """Records a lower-tier purchase to take effect once the current
    (higher) subscription period ends, without touching the active tier or
    expiry now.
    """
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "UPDATE subscriptions SET pending_tier = ? WHERE telegram_id = ?",
            (pending_tier, telegram_id),
        )
        await db.commit()


async def get_lapsed_subscriptions() -> list[aiosqlite.Row]:
    """Subscriptions whose expires_at has passed — the daily expiry job's
    input. Each row carries any queued pending_tier so the caller can apply
    it instead of just downgrading to free.
    """
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT telegram_id, pending_tier FROM subscriptions WHERE expires_at <= datetime('now')"
        )
        return await cursor.fetchall()


async def downgrade_to_free(telegram_id: int) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            f"UPDATE users SET subscription_tier = '{_DEFAULT_TIER}' WHERE telegram_id = ?",
            (telegram_id,),
        )
        await db.commit()


async def log_usage(
    telegram_id: int,
    action_type: str,
    move_number: int | None = None,
    move_san: str | None = None,
    context_san: str | None = None,
    cp_loss: int | None = None,
) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO usage (telegram_id, action_type, move_number, move_san, context_san, cp_loss)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (telegram_id, action_type, move_number, move_san, context_san, cp_loss),
        )
        await db.commit()


async def count_usage_last_24h(telegram_id: int, action_type: str) -> int:
    async with aiosqlite.connect(config.DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT COUNT(*) FROM usage
            WHERE telegram_id = ? AND action_type = ?
              AND timestamp >= datetime('now', '-1 day')
            """,
            (telegram_id, action_type),
        )
        row = await cursor.fetchone()
        return row[0]


async def count_usage_total(telegram_id: int, action_type: str) -> int:
    """All-time count, no time window — used for the free tier's one-time
    lifetime trial (see usage_service.get_remaining_analyses).
    """
    async with aiosqlite.connect(config.DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM usage WHERE telegram_id = ? AND action_type = ?",
            (telegram_id, action_type),
        )
        row = await cursor.fetchone()
        return row[0]


async def get_critical_moments_since(
    telegram_id: int, action_type: str, days: int, limit: int = 150
) -> list[aiosqlite.Row]:
    """Returns up to `limit` of the user's most recent logged moments from
    the last `days` days, oldest first.
    """
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT move_number, move_san, context_san, cp_loss, timestamp
            FROM usage
            WHERE telegram_id = ? AND action_type = ?
              AND timestamp >= datetime('now', ?)
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (telegram_id, action_type, f"-{days} days", limit),
        )
        rows = await cursor.fetchall()
        return list(reversed(rows))


async def log_token_usage(
    telegram_id: int, input_tokens: int, output_tokens: int, cached_tokens: int
) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO token_usage (telegram_id, input_tokens, output_tokens, cached_tokens)
            VALUES (?, ?, ?, ?)
            """,
            (telegram_id, input_tokens, output_tokens, cached_tokens),
        )
        await db.commit()


async def save_analysis(telegram_id: int, request_text: str, result_text: str) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "INSERT INTO analyses (telegram_id, request_text, result_text) VALUES (?, ?, ?)",
            (telegram_id, request_text, result_text),
        )
        await db.commit()


async def get_user_analyses(telegram_id: int, limit: int = 10) -> list[aiosqlite.Row]:
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM analyses WHERE telegram_id = ? ORDER BY created_at DESC LIMIT ?",
            (telegram_id, limit),
        )
        return await cursor.fetchall()


async def bulk_insert_puzzles(rows: list[tuple]) -> int:
    """Inserts puzzle rows as (puzzle_id, fen, solution, rating,
    rating_deviation, popularity, themes) tuples. Existing puzzle_ids are
    left untouched, so re-running an import is safe. Returns how many rows
    were actually new.
    """
    async with aiosqlite.connect(config.DB_PATH) as db:
        cursor = await db.executemany(
            """
            INSERT OR IGNORE INTO puzzles
                (puzzle_id, fen, solution, rating, rating_deviation, popularity, themes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        await db.commit()
        return cursor.rowcount


async def count_puzzles() -> int:
    async with aiosqlite.connect(config.DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM puzzles")
        row = await cursor.fetchone()
        return row[0]


# Widen the rating window this many times before giving up, doubling the
# window on each attempt — keeps a request for a rare rating band (the
# extreme ends of the dataset) from ever 404ing in practice.
_PUZZLE_SEARCH_MAX_ATTEMPTS = 5


async def get_random_puzzle(rating_min: int, rating_max: int) -> aiosqlite.Row | None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        lo, hi = rating_min, rating_max
        for _ in range(_PUZZLE_SEARCH_MAX_ATTEMPTS):
            cursor = await db.execute(
                """
                SELECT puzzle_id, fen, solution, rating, rating_deviation, popularity, themes
                FROM puzzles
                WHERE rating BETWEEN ? AND ?
                ORDER BY RANDOM()
                LIMIT 1
                """,
                (lo, hi),
            )
            row = await cursor.fetchone()
            if row is not None:
                return row
            width = hi - lo
            lo, hi = lo - width, hi + width
        return None


async def get_random_puzzle_by_tags(
    rating_min: int, rating_max: int, tags: set[str]
) -> aiosqlite.Row | None:
    """Like get_random_puzzle, but restricted to puzzles whose themes
    intersect `tags`. Filtered in Python rather than with a chain of SQL
    LIKEs — themes is a space-separated string and the whole table is only
    a few thousand rows, so this stays fast without fragile boundary
    matching.
    """
    if not tags:
        return None

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        lo, hi = rating_min, rating_max
        for _ in range(_PUZZLE_SEARCH_MAX_ATTEMPTS):
            cursor = await db.execute(
                """
                SELECT puzzle_id, fen, solution, rating, rating_deviation, popularity, themes
                FROM puzzles
                WHERE rating BETWEEN ? AND ?
                """,
                (lo, hi),
            )
            rows = await cursor.fetchall()
            matches = [row for row in rows if set(row["themes"].split()) & tags]
            if matches:
                return random.choice(matches)
            width = hi - lo
            lo, hi = lo - width, hi + width
        return None


# Diamond-only: a missed day doesn't reset the streak if the last freeze was
# used at least this many days ago.
STREAK_FREEZE_COOLDOWN_DAYS = 30


def today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def is_streak_freeze_available(freeze_used_at: str | None) -> bool:
    if freeze_used_at is None:
        return True
    last_used = datetime.fromisoformat(freeze_used_at[:10]).date()
    today = datetime.now(timezone.utc).date()
    return (today - last_used).days >= STREAK_FREEZE_COOLDOWN_DAYS


async def get_latest_puzzle_stats(telegram_id: int) -> aiosqlite.Row | None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM puzzle_stats WHERE telegram_id = ? ORDER BY date DESC LIMIT 1",
            (telegram_id,),
        )
        return await cursor.fetchone()


async def record_puzzle_solved(telegram_id: int, freeze_eligible: bool) -> tuple[aiosqlite.Row, bool]:
    """Records one solved puzzle for `telegram_id` today and updates the
    streak. Returns (the resulting today's row, whether a streak freeze was
    applied this call).

    Streak rules: solving again the same day just bumps solved_count.
    Solving on the very next calendar day bumps streak_days by one. Missing
    exactly one day resets streak_days to 1 — unless `freeze_eligible` is
    True (caller has already checked the Diamond tier) and a freeze hasn't
    been used within STREAK_FREEZE_COOLDOWN_DAYS, in which case the gap is
    bridged as if it hadn't happened. Missing two or more days always
    resets, regardless of tier — the freeze only covers a single missed day.
    """
    today = today_str()

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            "SELECT * FROM puzzle_stats WHERE telegram_id = ? AND date = ?",
            (telegram_id, today),
        )
        existing_today = await cursor.fetchone()

        if existing_today is not None:
            await db.execute(
                """
                UPDATE puzzle_stats SET solved_count = solved_count + 1
                WHERE telegram_id = ? AND date = ?
                """,
                (telegram_id, today),
            )
            await db.commit()
            cursor = await db.execute(
                "SELECT * FROM puzzle_stats WHERE telegram_id = ? AND date = ?",
                (telegram_id, today),
            )
            return await cursor.fetchone(), False

        cursor = await db.execute(
            "SELECT * FROM puzzle_stats WHERE telegram_id = ? ORDER BY date DESC LIMIT 1",
            (telegram_id,),
        )
        previous = await cursor.fetchone()

        freeze_applied = False
        if previous is None:
            new_streak = 1
            new_freeze_used_at = None
        else:
            gap_days = (
                datetime.fromisoformat(today).date()
                - datetime.fromisoformat(previous["date"]).date()
            ).days
            if gap_days == 1:
                new_streak = previous["streak_days"] + 1
                new_freeze_used_at = previous["streak_freeze_used_at"]
            elif (
                gap_days == 2
                and freeze_eligible
                and is_streak_freeze_available(previous["streak_freeze_used_at"])
            ):
                new_streak = previous["streak_days"] + 1
                new_freeze_used_at = today
                freeze_applied = True
            else:
                new_streak = 1
                new_freeze_used_at = previous["streak_freeze_used_at"]

        await db.execute(
            """
            INSERT INTO puzzle_stats (telegram_id, date, solved_count, streak_days, streak_freeze_used_at)
            VALUES (?, ?, 1, ?, ?)
            """,
            (telegram_id, today, new_streak, new_freeze_used_at),
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT * FROM puzzle_stats WHERE telegram_id = ? AND date = ?",
            (telegram_id, today),
        )
        return await cursor.fetchone(), freeze_applied
