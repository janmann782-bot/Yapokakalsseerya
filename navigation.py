"""Human-facing navigation, creation choices and section-based editing."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup

from drafts import checkpoint, park_flow
from locales import tr
from hoi4_limits import news_data_error
from parser import parse_text
from states import Navigation, NewPage, clear_flow
from templates import TEMPLATES, get_template
from themes import theme_allowed
from ui import home_kb, ib, types_kb, field_sections_kb, field_group_kb, pages_kb, flow_show

router = Router(name="navigation")


async def screen(target, text, markup):
    msg = target.message if hasattr(target, "message") else target
    if hasattr(target, "message") and getattr(msg, "text", None) and callable(getattr(msg, "edit_text", None)):
        from aiogram.exceptions import TelegramBadRequest
        try:
            return await msg.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return msg
    return await msg.answer(text, reply_markup=markup, parse_mode="HTML")


async def show_home(target, state, db, user_id):
    await park_flow(state, user_id, db)
    draft = await db.get_draft(user_id)
    text = tr("welcome")
    if draft:
        title = (draft.get("page_data") or {}).get("title", "Без названия")
        from html import escape
        text += '\n\nЧерновик: "' + escape(str(title)) + '"'
    await screen(target, text, home_kb(bool(draft)))


@router.callback_query(F.data.startswith("nav:"))
async def navigate(q: CallbackQuery, state: FSMContext, db, cfg):
    from handlers import show_settings, statistics
    await q.answer()
    action = q.data.split(":")[1]
    if action == "create":
        await park_flow(state, q.from_user.id, db)
        await screen(q, tr("choose_type"), types_kb())
    elif action == "settings":
        await park_flow(state, q.from_user.id, db)
        await show_settings(q.message, db, q.from_user.id)
    elif action == "help":
        await park_flow(state, q.from_user.id, db)
        await screen(q, tr("help"), home_kb(bool(await db.get_draft(q.from_user.id))))
    elif action == "stats":
        await statistics(q.message, db, user_id=q.from_user.id)


@router.callback_query(F.data == "compose:finish")
async def finish_wizard(q: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    if not d.get("type") or not (d.get("page_data") or {}).get("title"):
        await q.answer(tr("title_required"), show_alert=True)
        return
    await q.answer()
    await state.set_state(NewPage.review)
    await flow_show(q, state, tr("fields_title"), field_sections_kb(get_template(d["type"], d.get("page_data") or {}), d["page_data"]))


@router.callback_query(F.data.startswith("compose:"))
async def choose_method(q: CallbackQuery, state: FSMContext):
    await q.answer()
    kind = q.data.split(":")[1]
    if kind == "more":
        from ui import SPECIAL_TYPES
        rows = [[ib(TEMPLATES[k].label, f"compose:{k}")] for k in TEMPLATES if k in SPECIAL_TYPES]
        rows.append([ib("К основным форматам", "nav:create")])
        await screen(q, "<b>Еще форматы</b>\nВыбери что собираешь", InlineKeyboardMarkup(inline_keyboard=rows))
        return
    if kind not in TEMPLATES:
        return
    if kind == "superevent":
        from hoi4_handlers import style_kb
        await screen(q, "<b>HOI4 Карточка (бета)</b>\nВыбери стиль", style_kb("new"))
        return
    await method_screen(q, kind)


async def method_screen(q, kind):
    text = tr("method_choice", type=get_template(kind).label)
    await screen(q, text, InlineKeyboardMarkup(inline_keyboard=[
        [ib("Пройти по шагам", f"build:{kind}:wizard")],
        [ib("Вставить готовый текст", f"build:{kind}:paste")],
        [ib("Открыть редактор", f"build:{kind}:editor")],
        [ib("Другой тип", "nav:create"), ib("В меню", "menu:home")],
    ]))


@router.callback_query(F.data.startswith("build:"))
@router.callback_query(F.data.startswith("replace:"))
async def begin_method(q: CallbackQuery, state: FSMContext, db, cfg):
    await q.answer()
    prefix, kind, method = q.data.split(":")
    if kind not in TEMPLATES or method not in {"wizard", "paste", "editor"}:
        return
    selection = (await state.get_data()).get("hoi4_selection") if kind == "superevent" else None
    await checkpoint(state, db, q.from_user.id)
    draft = await db.get_draft(q.from_user.id)
    if draft and prefix != "replace":
        await screen(q, tr("draft_exists"), InlineKeyboardMarkup(inline_keyboard=[
            [ib("Продолжить старый", "draft:resume")],
            [ib("Удалить его и начать новый", f"replace:{kind}:{method}")],
            [ib("В меню", "menu:home")],
        ]))
        return
    if draft:
        await state.set_data(draft)
        await clear_flow(state, q.from_user.id, db, cfg)
        await db.delete_draft(q.from_user.id)
    else:
        await state.clear()
    if method == "paste":
        await state.set_state(Navigation.paste)
        await state.update_data(paste_type=kind, paste_hoi4=selection)
        await flow_show(q, state, tr("paste_prompt"), InlineKeyboardMarkup(inline_keyboard=[[ib("Другой способ", f"compose:{kind}"), ib("В меню", "menu:home")]]))
        return
    from create_handlers import begin_new_page
    await begin_new_page(q.message, state, db, cfg, q.from_user.id, kind, user=q.from_user, initial_data=selection)
    if method == "editor":
        await state.update_data(creation_mode="editor")


@router.message(Navigation.paste, F.text)
async def paste_data(msg: Message, state: FSMContext, db, cfg):
    from create_handlers import quick_summary, show_quick
    d = await state.get_data()
    kind = d["paste_type"]
    parsed = parse_text("Тип: " + get_template(kind).label + "\n" + msg.text)
    error = news_data_error(parsed.type,parsed.data)
    if error:
        await msg.answer(error)
        return
    if not parsed.data.get("title"):
        await msg.answer(tr("paste_need_title"))
        return
    if kind == "superevent":
        parsed.data.update(d.get("paste_hoi4") or {})
    settings = await db.get_settings(msg.from_user.id)
    extra = tr("quick_unknown", lines="\n".join(parsed.unknown[:8])) if parsed.unknown else ""
    if parsed.warnings:
        extra += tr("quick_warnings", lines="\n".join(parsed.warnings[:6]))
    quick = tr("quick_found", count=parsed.recognized, type=get_template(parsed.type).label, summary=quick_summary(parsed), extra=extra)
    await state.set_data(dict(type=parsed.type, page_data=parsed.data, theme=("tno" if parsed.data.get("hoi4_style") == "tno" else "fire_rises") if kind == "superevent" else settings.theme if theme_allowed(settings.theme, parsed.type) else "light", quick_text=quick[:4000], max_image_mb=cfg.max_image_mb))
    await show_quick(msg, state)


@router.callback_query(F.data == "draft:resume")
async def resume_draft(q: CallbackQuery, state: FSMContext, db, cfg):
    await q.answer()
    await checkpoint(state, db, q.from_user.id)
    draft = await db.get_draft(q.from_user.id)
    if not draft:
        await screen(q, tr("draft_missing"), home_kb())
        return
    await state.set_data(draft)
    await state.set_state(NewPage.review)
    tpl = get_template(draft["type"], draft.get("page_data") or {})
    await flow_show(q, state, tr("draft_resumed"), field_sections_kb(tpl, draft.get("page_data") or {}))


@router.callback_query(F.data.in_({"draft:discard", "draft:discard:yes"}))
async def discard_draft(q: CallbackQuery, state: FSMContext, db, cfg):
    await q.answer()
    if q.data == "draft:discard":
        await screen(q, tr("discard_prompt"), InlineKeyboardMarkup(inline_keyboard=[[ib("Да, удалить черновик", "draft:discard:yes")], [ib("Оставить", "menu:home")]]))
        return
    draft = await db.get_draft(q.from_user.id)
    if draft:
        await state.set_data(draft)
    await clear_flow(state, q.from_user.id, db, cfg)
    await db.delete_draft(q.from_user.id)
    await show_home(q, state, db, q.from_user.id)


@router.callback_query(F.data.startswith("group:"))
async def show_group(q: CallbackQuery, state: FSMContext, db):
    await q.answer()
    _, scope, kind, raw_index, raw_offset = q.data.split(":")
    if scope == "d":
        d = await state.get_data()
        if not d.get("type"):
            await screen(q, tr("draft_missing"), home_kb(bool(await db.get_draft(q.from_user.id))))
            return
        tpl, values = get_template(d["type"], d.get("page_data") or {}), d.get("page_data") or {}
        await state.set_state(NewPage.review)
    else:
        page = await db.get_page(int(scope[1:]), q.from_user.id)
        if page is None:
            await screen(q, tr("page_not_found"), home_kb())
            return
        tpl, values = get_template(page.type, page.data), page.data
    try:
        name, markup = field_group_kb(tpl, values, scope, kind, int(raw_index), int(raw_offset))
    except (ValueError, IndexError, KeyError):
        await q.message.answer(tr("section_gone"))
        return
    await flow_show(q, state, tr("group_prompt", name=name), markup)


async def show_cards(target, state, db, user_id, offset=0, query=None):
    if query is None:
        query = (await state.get_data()).get("card_query", "")
    await state.update_data(card_query=query)
    pages = await db.search_pages(user_id, query, max(0, offset), 9)
    text = tr("pages_title") if pages else tr("cards_not_found" if query else "pages_empty")
    if query:
        text += "\n\n" + tr("search_caption", query=query)
    await screen(target, text, pages_kb(pages[:8], offset, len(pages) > 8))


@router.callback_query(F.data == "cards:search")
async def search_cards(q: CallbackQuery, state: FSMContext, db):
    await q.answer()
    await park_flow(state, q.from_user.id, db)
    await state.set_state(Navigation.search)
    await screen(q, tr("search_prompt"), InlineKeyboardMarkup(inline_keyboard=[[ib("Все мои карточки", "pages:list"), ib("В меню", "menu:home")]]))


@router.message(Navigation.search, F.text)
async def search_query(msg: Message, state: FSMContext, db):
    await state.clear()
    await show_cards(msg, state, db, msg.from_user.id, query=msg.text.strip()[:200])


@router.callback_query(F.data.startswith("cards:"))
async def card_page(q: CallbackQuery, state: FSMContext, db):
    await q.answer()
    try:
        offset = max(0, int(q.data.split(":")[1]))
    except ValueError:
        return
    await show_cards(q, state, db, q.from_user.id, offset)
