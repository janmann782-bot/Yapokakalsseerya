from __future__ import annotations

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation

from admin import maintenance_middleware, router as admin_router
from config import Config
from create_handlers import router as create_router
from battle_handlers import router as battle_router
from db import Db
from handlers import on_error
from handlers import router as common_router
from page_handlers import router as page_router
from navigation import router as navigation_router
from drafts import DraftCheckpointMiddleware, DraftPreviewRecoveryMiddleware
from hoi4_handlers import router as hoi4_router
from stamp_handlers import router as stamp_router


def make_dispatcher(db: Db, cfg: Config) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation())
    dp["db"] = db
    dp["cfg"] = cfg
    # Blocks non-admins when maintenance is on (admin commands still work)
    dp.message.middleware(maintenance_middleware)
    dp.callback_query.middleware(maintenance_middleware)
    dp.message.outer_middleware(DraftCheckpointMiddleware())
    dp.callback_query.outer_middleware(DraftCheckpointMiddleware())
    dp.callback_query.outer_middleware(DraftPreviewRecoveryMiddleware())
    # Admin router first so /maint_* always reachable for admins
    dp.include_router(admin_router)
    dp.include_router(common_router)
    dp.include_router(hoi4_router)
    dp.include_router(stamp_router)
    dp.include_router(navigation_router)
    dp.include_router(page_router)
    dp.include_router(create_router)
    dp.include_router(battle_router)
    dp.errors()(on_error)
    return dp
