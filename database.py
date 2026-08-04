"""SQLite access layer built on aiosqlite."""
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
    subscription_tier TEXT NOT NULL DEFAULT '{_DEFAULT_TIER}'
        CHECK (subscription_tier IN ('free', 'ruby', 'emerald')),
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
    tier TEXT NOT NULL CHECK (tier IN ('ruby', 'emerald')),
    expires_at TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
);
"""


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


async def upsert_subscription(telegram_id: int, tier: str, expires_at: str) -> None:
    """Activates or upgrades a subscription — one active period per user,
    never two in parallel.
    """
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO subscriptions (telegram_id, tier, expires_at) VALUES (?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                tier = excluded.tier,
                expires_at = excluded.expires_at
            """,
            (telegram_id, tier, expires_at),
        )
        await db.commit()


async def expire_subscriptions() -> int:
    """Downgrades every user whose subscription has lapsed back to the free
    tier. Returns how many users were downgraded.
    """
    async with aiosqlite.connect(config.DB_PATH) as db:
        cursor = await db.execute(
            f"""
            UPDATE users
            SET subscription_tier = '{_DEFAULT_TIER}'
            WHERE subscription_tier != '{_DEFAULT_TIER}'
              AND telegram_id IN (
                  SELECT telegram_id FROM subscriptions WHERE expires_at <= datetime('now')
              )
            """
        )
        await db.commit()
        return cursor.rowcount


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
