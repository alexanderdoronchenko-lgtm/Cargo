from aiogram import Router

from handlers.start import router as start_router
from handlers.analysis import router as analysis_router

main_router = Router()
main_router.include_router(start_router)
main_router.include_router(analysis_router)
