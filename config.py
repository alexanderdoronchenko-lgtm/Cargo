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
# new users" 404). gemini-3.6-flash (the GA default used until now) has a
# tight free-tier quota; trying gemini-3-flash-preview instead — early
# reports point to a much more generous free-tier requests/day quota and
# lower per-token pricing, but it's a preview model, so Google can change
# or retire it with less notice than a GA release, and preview quotas are
# reported to shift over time too. Note the exact id: the model is NOT
# aliased as bare "gemini-3-flash" (that 404s) — it's "-preview". Re-check
# https://ai.google.dev/gemini-api/docs/models if this 404s or the quota
# turns out not to hold up in practice.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")

# A review now fires several parallel Gemini calls (batched explanations +
# a summary call — see services/commentary_service.py's Gemini path)
# instead of one, across potentially several simultaneous users' reviews.
# These two together protect the API key's limits — see
# services/commentary_service.py's _RateLimiter docstring for why a
# concurrency cap alone doesn't bound requests/minute.
#
# GEMINI_MAX_CONCURRENT_REQUESTS: how many Gemini calls may be in flight
# at once, process-wide. 12 leaves headroom for 2-3 users' reviews to run
# concurrently (each peaking at 4-5 in-flight calls) rather than
# serializing to one review at a time.
GEMINI_MAX_CONCURRENT_REQUESTS = int(os.getenv("GEMINI_MAX_CONCURRENT_REQUESTS", "12"))
# GEMINI_MAX_REQUESTS_PER_MINUTE: matches the Google AI Studio free tier's
# 15 RPM quota, with 1 request of headroom — raise this if the key is on a
# paid tier with a higher quota.
GEMINI_MAX_REQUESTS_PER_MINUTE = int(os.getenv("GEMINI_MAX_REQUESTS_PER_MINUTE", "14"))

# The google-genai SDK applies NO request timeout at all when this isn't
# set (confirmed: HttpOptions.timeout defaults to None, which becomes
# aiohttp.ClientTimeout(total=None) — genuinely unbounded, not just "a
# generous default"). Combined with attempts=1 (see gemini_service.py, no
# SDK-level retries), a single slow response — confirmed in production
# during a billing-tier transition, where Google itself warns of up to
# 24h propagation delay — can stall a whole review for minutes with
# nothing to time it out. 30s is generous for a real (if slow) response
# while still bounding the worst case; real successful calls have been
# measured at a few seconds.
GEMINI_REQUEST_TIMEOUT_SECONDS = int(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "30"))

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
RUBY_PRICE_STARS = int(os.getenv("RUBY_PRICE_STARS", "500"))
EMERALD_PRICE_STARS = int(os.getenv("EMERALD_PRICE_STARS", "600"))
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
