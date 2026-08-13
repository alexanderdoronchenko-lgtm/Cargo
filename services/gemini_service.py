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
# With no timeout set, the SDK applies none at all (HttpOptions.timeout
# defaults to None, which becomes aiohttp.ClientTimeout(total=None) —
# genuinely unbounded) — combined with attempts=1 above, a single slow
# response has nothing to time it out and can stall a whole review for
# minutes. Confirmed in production during a billing-tier transition
# (Google warns these can take up to 24h to fully propagate): non-cached
# input/output tokens came back real and non-zero (the call succeeded),
# it just took minutes to respond. See config.GEMINI_REQUEST_TIMEOUT_SECONDS.
client = genai.Client(
    api_key=config.GEMINI_API_KEY,
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(attempts=1),
        timeout=config.GEMINI_REQUEST_TIMEOUT_SECONDS * 1000,
    ),
)
