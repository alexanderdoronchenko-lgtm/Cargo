"""Application configuration loaded from environment variables (.env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

BOT_TOKEN = os.getenv("BOT_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

# Google AI Studio key for Gemini — used for Free/Ruby/Emerald review
# generation (see services/commentary_service.py's tier->provider routing).
# Diamond stays on Claude. Get a key at https://aistudio.google.com/apikey
# (free Google account, no billing setup needed for the free tier itself).
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# gemini-2.5-flash was retired for new API keys ("no longer available to
# new users" 404) — gemini-3.6-flash is the current GA Flash model as of
# August 2026 (launched 2026-07-21). Re-check
# https://ai.google.dev/gemini-api/docs/models if this 404s again; Google
# has been cycling Flash generations roughly every few months.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "bot.db"))
STOCKFISH_PATH = os.getenv("STOCKFISH_PATH")
# UCI "Threads" option — lets Stockfish search a single position with
# multiple worker threads instead of one. Only helps when there are that
# many real cores to give them: measured on a single pinned core, Threads=4
# reached a *shallower* effective depth than Threads=1 at the same time
# budget (11 vs 14 plies on a test position) — Lazy SMP's inter-thread
# synchronization overhead with no second core to run on, not a speedup.
# Auto-detecting the core count (capped at 4) keeps the default safe on
# small single-core droplets without needing manual tuning; override via
# env var if the server's core count changes.
STOCKFISH_THREADS = int(os.getenv("STOCKFISH_THREADS", str(min(4, os.cpu_count() or 1))))

# How many Claude API calls the review pipeline may have in flight at once
# (per-moment explanation calls + the summary call, fired concurrently
# instead of sequentially). This is bounded by Anthropic rate limits, not
# local CPU/cores — safe to raise independently of server size.
CLAUDE_MAX_CONCURRENT_REQUESTS = int(os.getenv("CLAUDE_MAX_CONCURRENT_REQUESTS", "5"))

# Subscription prices in Telegram Stars (XTR), per month.
RUBY_PRICE_STARS = int(os.getenv("RUBY_PRICE_STARS", "600"))
EMERALD_PRICE_STARS = int(os.getenv("EMERALD_PRICE_STARS", "750"))
DIAMOND_PRICE_STARS = int(os.getenv("DIAMOND_PRICE_STARS", "3200"))

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

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set. Add it to your .env file.")
