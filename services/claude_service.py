"""Wrapper around the Claude (Anthropic) API."""
from anthropic import AsyncAnthropic

import config

client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)


async def ask_claude(prompt: str, system_prompt: str | None = None) -> str:
    """Send a prompt to Claude and return the plain-text reply."""
    response = await client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
        system=system_prompt or "You are a helpful assistant.",
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")
