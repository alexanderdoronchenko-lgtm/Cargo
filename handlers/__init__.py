from aiogram import Router

from handlers.start import router as start_router
from handlers.help import router as help_router
from handlers.language import router as language_router
from handlers.balance import router as balance_router
from handlers.game import router as game_router

main_router = Router()
main_router.include_router(start_router)
main_router.include_router(help_router)
main_router.include_router(language_router)
main_router.include_router(balance_router)
main_router.include_router(game_router)
