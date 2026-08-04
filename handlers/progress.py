import html

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import database
from locales import t
from services import progress_service
from services.usage_service import ACTION_CRITICAL_MOMENT

router = Router()

_PROGRESS_WINDOW_DAYS = 30


@router.message(Command("progress"))
async def cmd_progress(message: Message) -> None:
    telegram_id = message.from_user.id
    lang = await database.get_or_create_user(
        telegram_id, message.from_user.username, message.from_user.language_code
    )

    moments = await database.get_critical_moments_since(
        telegram_id, ACTION_CRITICAL_MOMENT, _PROGRESS_WINDOW_DAYS
    )
    if not moments:
        await message.answer(t("progress_no_data", lang))
        return

    await message.answer(t("progress_analyzing", lang))

    summary = await progress_service.summarize_weaknesses(moments, lang)
    # No formatting is requested from Claude here (plain text), but the
    # message still goes out under parse_mode=HTML — escape defensively so
    # an incidental "<", ">" or "&" in the model's prose can't be misparsed
    # as markup and reject the send.
    await message.answer(f"{t('progress_header', lang)}\n\n{html.escape(summary)}")
