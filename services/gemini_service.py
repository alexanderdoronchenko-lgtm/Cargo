"""Wrapper around the Gemini (Google AI Studio) API."""
from google import genai
from google.genai import types

import config

# The SDK retries 408/429/5xx up to 5 times by default (1s, 2s, 4s, 8s, ...
# exponential backoff) — reasonable for a caller with no retry strategy of
# its own, but this project already has one purpose-built for Gemini calls:
# commentary_service.py's _gemini_semaphore/_gemini_rate_limiter throttle
# calls *before* they're sent, and every call site has its own explicit
# fallback on failure. Letting the SDK also silently retry underneath means
# one logical call can balloon into 5 real HTTP round trips plus tens of
# seconds of sleep, invisible to (and not counted against) that rate
# limiter — confirmed in production: a review whose Gemini stage should
# take 5-20s took 311s, because every batch/summary call first tried (and,
# on this free-tier key, always failed) to create an explicit cache, and
# each failed attempt was itself retried up to 5 times before finally
# giving up and falling back. attempts=1 disables SDK-level retries
# entirely so a failure surfaces immediately to this project's own
# handling instead of retrying blind.
client = genai.Client(
    api_key=config.GEMINI_API_KEY,
    http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
)
