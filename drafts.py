"""Keep the current draft when the user leaves the editor or the bot restarts."""

from aiogram import BaseMiddleware


async def checkpoint(state, db, user_id: int) -> None:
    data = await state.get_data()
    if data.get("type") and data.get("page_data"):
        payload = {
            k: v
            for k, v in data.items()
            if k not in {"flow_message_id", "flow_chat_id"}
        }
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


class DraftPreviewRecoveryMiddleware(BaseMiddleware):
    """Preview actions keep working after home navigation or an FSM restart."""

    async def __call__(self, handler, event, data):
        callback = getattr(event, "data", "") or ""
        direct = {
            "draft:save",
            "draft:fields",
            "draft:back",
            "draft:export",
            "draft:text",
            "draft:image",
            "draft:theme",
        }
        is_draft = callback in direct or callback.startswith(
            ("df:", "dc:", "dx:", "fields:d:", "group:d:")
        )
        if callback.startswith("hoi4:"):
            parts = callback.split(":")
            is_draft = len(parts) > 2 and parts[2] == "d"
        state, db = data.get("state"), data.get("db")
        if is_draft and state and db:
            current = await state.get_data()
            if not current.get("type"):
                stored = await db.get_draft(event.from_user.id)
                if stored:
                    from states import NewPage

                    await state.set_data(stored)
                    await state.set_state(NewPage.review)
                    current = stored
                else:
                    from ui import home_kb

                    await event.answer()
                    await event.message.answer(
                        'Этот черновик уже закрыт. Сохраненные карточки находятся в разделе "Мои карточки"',
                        reply_markup=home_kb(),
                    )
                    return
            # A stale preview must never edit a different, newer draft.
            previews = current.get("preview_messages") or []
            msg = event.message
            if callback in direct and msg.photo and previews:
                if not any(
                    p.get("chat_id") == msg.chat.id
                    and p.get("message_id") == msg.message_id
                    for p in previews
                ):
                    await event.answer(
                        "Это старый предпросмотр. Открой текущий черновик из меню",
                        show_alert=True,
                    )
                    return
        return await handler(event, data)


async def remember_preview(state, message):
    current = await state.get_data()
    previews = list(current.get("preview_messages") or [])
    item = {"chat_id": message.chat.id, "message_id": message.message_id}
    if item not in previews:
        previews.append(item)
    await state.update_data(preview_messages=previews)
