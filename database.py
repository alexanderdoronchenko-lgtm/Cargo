"""SQLite access layer built on aiosqlite."""
import aiosqlite

import config
from locales import DEFAULT_LANG, resolve_lang

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    language TEXT NOT NULL DEFAULT '{DEFAULT_LANG}',
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
"""


async def init_db() -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.executescript(_SCHEMA)
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
