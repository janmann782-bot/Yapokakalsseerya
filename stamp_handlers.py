"""Stamp-specific ink and font controls for drafts and saved pages."""
from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from PIL import ImageFont

from config import Config
from db import Db
from fonts_catalog import all_font_choices, user_fonts_dir
from states import StampFontUpload, NewPage
from stamp_renderer import stamp_image, wear_level
from ui import ib

router = Router(name="stamps")
MAX_FONT_BYTES = 5 * 1024 * 1024


def font_id(key):
    return hashlib.sha256(key.encode()).hexdigest()[:12]


async def target(scope, state, db, uid):
    if scope == "d":
        d = await state.get_data()
        if d.get("type") != "stamp":
            return None
        from create_handlers import make_draft
        return make_draft(d, uid)
    if scope.startswith("p") and scope[1:].isdigit():
        p = await db.get_page(int(scope[1:]), uid)
        return p if p and p.type == "stamp" else None
    return None


async def apply(msg, user, scope, p, state, db, cfg):
    if scope == "d":
        from create_handlers import show_preview
        await state.update_data(page_data=p.data, stamp_font_scope=None)
        await show_preview(msg, state, db, cfg, msg.bot, user)
    else:
        from page_handlers import render_saved
        p.preview_path = None
        await db.update_page(p)
        if await state.get_state() == StampFontUpload.wait.state:
            await state.set_state(NewPage.review if (await state.get_data()).get("type") else None)
        await state.update_data(stamp_font_scope=None)
        await render_saved(msg, p, db, cfg)


def back_kb(scope):
    return InlineKeyboardMarkup(inline_keyboard=[[ib("Назад к печати", f"stamp:back:{scope}")]])


@router.callback_query(F.data.startswith("stamp:fonts:"))
async def fonts(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config):
    _, _, scope, raw_page = q.data.split(":")
    p = await target(scope, state, db, q.from_user.id)
    if not p:
        await q.answer("Печать не найдена", show_alert=True)
        return
    await q.answer()
    choices = all_font_choices(cfg.work_dir, q.from_user.id)
    page = max(0, min(int(raw_page), (len(choices)-1)//8))
    selected = p.data.get("stamp_font") or p.data.get("_font_key") or "default"
    rows = [[ib(("✓ " if key == selected else "") + name, f"stamp:set:{scope}:{font_id(key)}")]
            for key, name in choices[page*8:page*8+8]]
    nav = []
    if page:
        nav.append(ib("◀", f"stamp:fonts:{scope}:{page-1}"))
    if (page+1)*8 < len(choices):
        nav.append(ib("▶", f"stamp:fonts:{scope}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.extend([[ib("Загрузить шрифт TTF / OTF", f"stamp:upload:{scope}")],
                 [ib("Назад к печати", f"stamp:back:{scope}")]])
    await q.message.answer("Шрифт печати\nВыбери из списка или загрузи свой TTF / OTF", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def choose_font(msg, user, scope, p, key, state, db, cfg):
    candidate = dict(p.data, stamp_font=key, _font_user_id=user.id)
    try:
        await asyncio.to_thread(stamp_image, candidate, cfg.work_dir)
    except (ValueError, OSError):
        await msg.answer("Шрифт не подходит для этих надписей. Выбери другой или сократи текст", reply_markup=back_kb(scope))
        return False
    p.data = candidate
    await apply(msg, user, scope, p, state, db, cfg)
    return True


@router.callback_query(F.data.startswith("stamp:set:"))
async def set_font(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config):
    _, _, scope, token = q.data.split(":")
    p = await target(scope, state, db, q.from_user.id)
    choices = all_font_choices(cfg.work_dir, q.from_user.id)
    key = next((key for key, _ in choices if font_id(key) == token), None)
    if not p or key is None:
        await q.answer("Открой список шрифтов заново", show_alert=True)
        return
    await q.answer()
    await choose_font(q.message, q.from_user, scope, p, key, state, db, cfg)


@router.callback_query(F.data.startswith("stamp:upload:"))
async def upload_start(q: CallbackQuery, state: FSMContext, db: Db):
    scope = q.data.split(":")[2]
    if not await target(scope, state, db, q.from_user.id):
        await q.answer("Печать не найдена", show_alert=True)
        return
    await q.answer()
    await state.update_data(stamp_font_scope=scope)
    await state.set_state(StampFontUpload.wait)
    await q.message.answer("Пришли шрифт файлом .ttf или .otf до 5 МБ", reply_markup=back_kb(scope))


@router.message(StampFontUpload.wait)
async def upload(msg: Message, state: FSMContext, db: Db, cfg: Config):
    scope = (await state.get_data()).get("stamp_font_scope", "")
    p = await target(scope, state, db, msg.from_user.id)
    if not p:
        await msg.answer("Печать не найдена. Открой редактор заново")
        return
    doc = msg.document
    suffix = Path(doc.file_name or "").suffix.lower() if doc else ""
    if suffix not in (".ttf", ".otf"):
        await msg.answer("Нужен файл .ttf или .otf", reply_markup=back_kb(scope))
        return
    if (doc.file_size or 0) > MAX_FONT_BYTES:
        await msg.answer("Шрифт должен быть не больше 5 МБ", reply_markup=back_kb(scope))
        return
    buf = BytesIO()
    await msg.bot.download(doc, destination=buf)
    content = buf.getvalue()
    if len(content) > MAX_FONT_BYTES:
        await msg.answer("Шрифт должен быть не больше 5 МБ", reply_markup=back_kb(scope))
        return
    try:
        ImageFont.truetype(BytesIO(content), 40)
    except (ValueError, OSError):
        await msg.answer("Файл не читается как шрифт. Пришли другой TTF или OTF", reply_markup=back_kb(scope))
        return
    stem = "".join(c for c in Path(doc.file_name).stem if c.isalnum() or c in "-_")[:30] or "Шрифт"
    filename = f"{stem}_{uuid4().hex[:10]}{suffix}"
    path = user_fonts_dir(cfg.work_dir, msg.from_user.id) / filename
    path.write_bytes(content)
    if not await choose_font(msg, msg.from_user, scope, p, f"user:{filename}", state, db, cfg):
        path.unlink(missing_ok=True)


@router.callback_query(F.data.startswith("stamp:reroll:"))
async def reroll(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config):
    scope = q.data.split(":")[2]
    p = await target(scope, state, db, q.from_user.id)
    if not p:
        await q.answer("Печать не найдена", show_alert=True)
        return
    await q.answer()
    p.data["stamp_seed"] = uuid4().hex
    if not wear_level(p.data):
        p.data["stamp_wear"] = "35"
    await apply(q.message, q.from_user, scope, p, state, db, cfg)


@router.callback_query(F.data.startswith("stamp:back:"))
async def back(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config):
    scope = q.data.split(":")[2]
    p = await target(scope, state, db, q.from_user.id)
    await q.answer()
    if p:
        await apply(q.message, q.from_user, scope, p, state, db, cfg)
