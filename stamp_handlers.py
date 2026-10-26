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
from states import StampFontUpload, StampDocument, NewPage
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
        doc = document_path(await state.get_data(),cfg,q.from_user.id)
        if doc:
            doc.unlink(missing_ok=True)
        await state.update_data(stamp_document_file=None)
        await apply(q.message, q.from_user, scope, p, state, db, cfg)


@router.callback_query(F.data.startswith("stamp:options:"))
async def options(q: CallbackQuery, state: FSMContext, db: Db):
    from stamp_controls import settings_kb
    scope = q.data.split(":")[2]
    if not await target(scope, state, db, q.from_user.id):
        await q.answer("Печать не найдена", show_alert=True)
        return
    await q.answer()
    await q.message.answer("Оформление печати", reply_markup=settings_kb(scope))


@router.callback_query(F.data.startswith("stamp:option:"))
async def option(q: CallbackQuery, state: FSMContext, db: Db):
    from stamp_controls import option_kb, LABELS
    _,_,scope,key = q.data.split(":")
    if key not in LABELS or not await target(scope, state, db, q.from_user.id):
        await q.answer("Печать не найдена", show_alert=True)
        return
    await q.answer()
    text = LABELS[key]
    if key == "stamp_logo_mode":
        text += "\nЗагрузи PNG через «Картинки», затем выбери расположение герба"
    base = InlineKeyboardMarkup(inline_keyboard=[[ib("К настройкам", f"stamp:options:{scope}")]])
    if key in ("stamp_color", "stamp_wear", "stamp_width", "stamp_angle", "stamp_weight", "stamp_rings"):
        base.inline_keyboard.insert(0, [ib("Свое значение", f"stamp:custom:{scope}:{key}")])
    await q.message.answer(text, reply_markup=option_kb(key,scope,base))


@router.callback_query(F.data.startswith("stamp:custom:"))
async def custom_option(q: CallbackQuery, state: FSMContext, db: Db):
    from states import EditPage
    from field_validation import field_prompt
    from stamp_controls import LABELS
    _,_,scope,key = q.data.split(":")
    p = await target(scope, state, db, q.from_user.id)
    if not p or key not in ("stamp_color", "stamp_wear", "stamp_width", "stamp_angle", "stamp_weight", "stamp_rings"):
        await q.answer("Открой настройки заново", show_alert=True)
        return
    await q.answer()
    await state.update_data(edit_kind="standard" if scope == "d" else "s", edit_key=key,
                            edit_label=LABELS[key], page_id=p.id)
    await state.set_state(NewPage.edit_value if scope == "d" else EditPage.value)
    hint = {"stamp_width":"От 1 до 24", "stamp_angle":"От -30 до 30 градусов"}.get(key, "")
    await q.message.answer(LABELS[key]+"\n"+hint+field_prompt("stamp",key), reply_markup=back_kb(scope))


@router.callback_query(F.data.startswith("stamp:pick:"))
async def pick(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config):
    from stamp_controls import OPTIONS
    from templates import get_template
    _,_,scope,key,index = q.data.split(":")
    choices = OPTIONS.get(key, [])
    if not index.isdigit() or not 0 <= int(index) < len(choices):
        await q.answer("Открой настройки заново", show_alert=True)
        return
    p = await target(scope, state, db, q.from_user.id)
    if not p:
        await q.answer("Печать не найдена", show_alert=True)
        return
    value = choices[int(index)][1]
    if scope == "d" and await state.get_state() == NewPage.field.state:
        d = await state.get_data()
        wizard = get_template("stamp").wizard
        i = d.get("i",0)
        if i >= len(wizard) or wizard[i] != key:
            await q.answer("Эта кнопка от другого шага", show_alert=True)
            return
        await q.answer()
        p.data[key] = value
        await state.update_data(page_data=p.data, i=i+1)
        from create_handlers import ask_field
        await ask_field(q.message, state)
        return
    await q.answer()
    candidate = dict(p.data, **{key:value})
    try:
        await asyncio.to_thread(stamp_image,candidate,cfg.work_dir)
    except (ValueError,OSError):
        await q.message.answer("Не получилось применить настройку. Проверь надписи и шрифт", reply_markup=back_kb(scope))
        return
    p.data = candidate
    await apply(q.message,q.from_user,scope,p,state,db,cfg)


@router.callback_query(F.data.startswith("stamp:presets:"))
async def presets(q: CallbackQuery, state: FSMContext, db: Db):
    from stamp_controls import PRESETS
    scope=q.data.split(":")[2]
    if scope != "new" and not await target(scope,state,db,q.from_user.id):
        await q.answer("Печать не найдена",show_alert=True)
        return
    await q.answer()
    rows=[[ib(name,f"stamp:preset:{scope}:{i}")] for i,name in enumerate(PRESETS)]
    rows.append([ib("Назад", "compose:stamp" if scope=="new" else f"stamp:options:{scope}")])
    await q.message.answer("Готовые штампы",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("stamp:preset:"))
async def preset(q: CallbackQuery, state: FSMContext, db: Db, cfg: Config):
    from stamp_controls import PRESETS
    _,_,scope,index=q.data.split(":")
    if not index.isdigit() or not 0 <= int(index) < len(PRESETS):
        await q.answer()
        return
    p=await target(scope,state,db,q.from_user.id)
    if scope!="new" and not p:
        await q.answer("Печать не найдена",show_alert=True)
        return
    await q.answer()
    name=PRESETS[int(index)]
    if scope=="new":
        from drafts import park_flow
        await park_flow(state,q.from_user.id,db,cfg)
        await state.update_data(type="stamp",theme="stamp",page_data={"title":name},max_image_mb=cfg.max_image_mb)
        p=await target("d",state,db,q.from_user.id)
        scope="d"
    p.data.update(stamp_shape="прямоугольная", stamp_center=name.upper(), stamp_top="", stamp_bottom="",
                  stamp_logo_mode="с текстом")
    # Presets use a single label without unused headline/footer dividers.
    p.data["stamp_preset"]=True
    from media import set_page_images
    set_page_images(p.data, [])
    await apply(q.message,q.from_user,scope,p,state,db,cfg)


def document_kb(scope, position=8, percent=25):
    labels=["↖","↑","↗","←","●","→","↙","↓","↘"]
    rows=[[ib(("✓ " if position==i else "")+labels[i],f"stamp:docpos:{scope}:{i}") for i in range(row*3,row*3+3)] for row in range(3)]
    rows.append([ib(("✓ " if percent==size else "")+str(size)+"%",f"stamp:docsize:{scope}:{size}") for size in (15,25,35,45)])
    rows.extend([[ib("Скачать PNG",f"stamp:docpng:{scope}")], [ib("Другой документ",f"stamp:document:{scope}"), ib("Назад к печати",f"stamp:back:{scope}")]])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def document_path(data,cfg,uid):
    name=data.get("stamp_document_file") or ""
    path=(cfg.work_dir/name).resolve()
    if path.parent!=cfg.work_dir.resolve() or not path.name.startswith(f"stampdoc_{uid}_") or not path.is_file():
        return None
    return path


async def show_document(msg,user,scope,state,db,cfg,export=False):
    from PIL import Image
    from stamp_document import place_stamp
    from ui import send_png
    d=await state.get_data()
    source=document_path(d,cfg,user.id)
    p=await target(scope,state,db,user.id)
    if not source or not p or d.get("stamp_document_scope")!=scope:
        await msg.answer("Пришли документ заново",reply_markup=back_kb(scope))
        return
    # Settings and seed come from the same page used by regular PNG export.
    p.data.setdefault("stamp_seed",uuid4().hex)
    settings=await db.get_settings(user.id)
    stamp_data=dict(p.data,_font_key=settings.font or "default",_font_user_id=user.id)
    stamp=await asyncio.to_thread(stamp_image,stamp_data,cfg.work_dir)
    with Image.open(source) as document:
        result=await asyncio.to_thread(place_stamp,document,stamp,d.get("stamp_document_pos",8),d.get("stamp_document_size",25))
    path=cfg.work_dir/f"stamped_{user.id}_{uuid4().hex}.png"
    try:
        await asyncio.to_thread(result.save,path,"PNG")
        await send_png(msg,path,"Печать на документе\nВыбери место и размер",document_kb(scope,d.get("stamp_document_pos",8),d.get("stamp_document_size",25)),export)
    finally:
        path.unlink(missing_ok=True)


@router.callback_query(F.data.startswith("stamp:document:"))
async def document_start(q: CallbackQuery,state:FSMContext,db:Db,cfg:Config):
    scope=q.data.split(":")[2]
    if not await target(scope,state,db,q.from_user.id):
        await q.answer("Печать не найдена",show_alert=True)
        return
    await q.answer()
    old=document_path(await state.get_data(),cfg,q.from_user.id)
    if old:
        old.unlink(missing_ok=True)
    await state.update_data(stamp_document_scope=scope,stamp_document_file=None,stamp_document_pos=8,stamp_document_size=25)
    await state.set_state(StampDocument.wait)
    await q.message.answer("Пришли изображение документа\nДля исходного качества отправь PNG файлом",reply_markup=back_kb(scope))


@router.message(StampDocument.wait)
async def document_receive(msg:Message,state:FSMContext,db:Db,cfg:Config):
    from stamp_document import read_document
    scope=(await state.get_data()).get("stamp_document_scope","")
    if not await target(scope,state,db,msg.from_user.id):
        await msg.answer("Печать не найдена")
        return
    attachment=msg.document or (msg.photo[-1] if msg.photo else None)
    if not attachment:
        await msg.answer("Пришли изображение документа",reply_markup=back_kb(scope))
        return
    if (attachment.file_size or 0)>cfg.max_image_mb*1024*1024:
        await msg.answer(f"Изображение должно быть не больше {cfg.max_image_mb} МБ",reply_markup=back_kb(scope))
        return
    buf=BytesIO()
    await msg.bot.download(attachment,destination=buf)
    try:
        image=await asyncio.to_thread(read_document,buf.getvalue(),cfg.max_image_mb)
    except ValueError as e:
        await msg.answer(str(e),reply_markup=back_kb(scope))
        return
    path=cfg.work_dir/f"stampdoc_{msg.from_user.id}_{uuid4().hex}.png"
    await asyncio.to_thread(image.save,path,"PNG")
    await state.update_data(stamp_document_file=path.name)
    await state.set_state(StampDocument.position)
    await show_document(msg,msg.from_user,scope,state,db,cfg)


@router.callback_query(F.data.startswith("stamp:docpos:"))
@router.callback_query(F.data.startswith("stamp:docsize:"))
@router.callback_query(F.data.startswith("stamp:docpng:"))
async def document_action(q:CallbackQuery,state:FSMContext,db:Db,cfg:Config):
    parts=q.data.split(":")
    action,scope=parts[1:3]
    d=await state.get_data()
    if d.get("stamp_document_scope")!=scope or not document_path(d,cfg,q.from_user.id):
        await q.answer("Пришли документ заново",show_alert=True)
        return
    if action!="docpng":
        if len(parts)!=4 or not parts[3].isdigit():
            await q.answer()
            return
        value=int(parts[3])
        if (action=="docpos" and value not in range(9)) or (action=="docsize" and value not in (15,25,35,45)):
            await q.answer()
            return
        await state.update_data(**{"stamp_document_pos" if action=="docpos" else "stamp_document_size":value})
    await q.answer()
    await show_document(q.message,q.from_user,scope,state,db,cfg,export=action=="docpng")
