"""Wrapper around the Gemini (Google AI Studio) API."""
from google import genai

import config

client = genai.Client(api_key=config.GEMINI_API_KEY)
