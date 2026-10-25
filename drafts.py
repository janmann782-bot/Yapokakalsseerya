"""Keep the current draft when the user leaves the editor or the bot restarts."""
from aiogram import BaseMiddleware


async def checkpoint(state, db, user_id: int) -> None:
    data = await state.get_data()
    if data.get("type") and data.get("page_data"):
        payload = {k: v for k, v in data.items() if k not in {"flow_message_id", "flow_chat_id"}}
        await db.save_draft(user_id, payload)


async def park_flow(state, user_id, db, cfg=None) -> None:
    await checkpoint(state, db, user_id)
    await state.clear()


async def invalidate_previews(db, cfg, user_id):
    from media import safe_unlink
    for path in await db.clear_previews(user_id):
        safe_unlink(path, cfg.work_dir, "preview_")
    draft = await db.get_draft(user_id)
    if draft:
        safe_unlink(draft.get("preview_path"), cfg.work_dir, "preview_")
        draft["preview_path"] = None
        await db.save_draft(user_id, draft)


class DraftCheckpointMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        result = await handler(event, data)
        state, db = data.get("state"), data.get("db")
        user = getattr(event, "from_user", None)
        if state and db and user:
            await checkpoint(state, db, user.id)
        return result
