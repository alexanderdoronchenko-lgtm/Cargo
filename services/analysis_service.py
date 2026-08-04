"""Analysis engine: turns a user request into a Claude-powered result and persists it."""
import database
from services.claude_service import ask_claude

_SYSTEM_PROMPT = (
    "You are an analysis engine. Carefully analyze the user's input and give "
    "a clear, structured, concise conclusion."
)


async def analyze(telegram_id: int, text: str) -> str:
    result = await ask_claude(text, system_prompt=_SYSTEM_PROMPT)
    await database.save_analysis(telegram_id, text, result)
    return result
