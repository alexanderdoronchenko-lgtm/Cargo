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
RUBY_PRICE_STARS = int(os.getenv("RUBY_PRICE_STARS", "600"))
EMERALD_PRICE_STARS = int(os.getenv("EMERALD_PRICE_STARS", "800"))
DIAMOND_PRICE_STARS = int(os.getenv("DIAMOND_PRICE_STARS", "1500"))

# Telegram Mini App URL — must be HTTPS (Telegram rejects http://). This is
# a placeholder until the Mini App is actually deployed; update the env var
# with the real URL, then register that same URL in BotFather via /newapp
# (see DEPLOYMENT.md for the exact steps).
MINIAPP_URL = os.getenv("MINIAPP_URL", "https://example.com/critical-moment-miniapp")

# Telegram user_id that gets unlimited access everywhere (game analyses,
# puzzles, opening trainer, streak freeze) regardless of actual
# subscription — for testing. Unset by default, so nobody gets this unless
# it's explicitly configured.
_admin_user_id_raw = os.getenv("ADMIN_USER_ID")
ADMIN_USER_ID = int(_admin_user_id_raw) if _admin_user_id_raw else None

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Add it to your .env file.")

if not ANTHROPIC_API_KEY:
    raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")
