"""Application configuration loaded from environment variables (.env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

BOT_TOKEN = os.getenv("BOT_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "bot.db"))
STOCKFISH_PATH = os.getenv("STOCKFISH_PATH")

# Subscription prices in Telegram Stars (XTR), per month.
RUBY_PRICE_STARS = int(os.getenv("RUBY_PRICE_STARS", "750"))
EMERALD_PRICE_STARS = int(os.getenv("EMERALD_PRICE_STARS", "1150"))
DIAMOND_PRICE_STARS = int(os.getenv("DIAMOND_PRICE_STARS", "1800"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Add it to your .env file.")

if not ANTHROPIC_API_KEY:
    raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")
