from aiogram import F, Router
from aiogram.types import Message

from services.analysis_service import analyze

router = Router()


@router.message(F.text)
async def handle_text(message: Message) -> None:
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        result = await analyze(message.from_user.id, message.text)
    except Exception:
        await message.answer("Не удалось выполнить анализ. Попробуйте позже.")
        raise
    await message.answer(result)
