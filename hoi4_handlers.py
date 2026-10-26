"""HOI4 format/style selection and explicitly assigned images."""

from html import escape
from io import BytesIO

from aiogram import F, Router
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup

from drafts import park_flow
from media import BadImage, save_image, set_page_images
from templates import HOI4_MODES
from hoi4_renderer import image_roles, media_roles, crop_settings
from ui import ib, flow_show
from states import NewPage
from aiogram.dispatcher.event.bases import SkipHandler

router = Router(name="hoi4")


class Hoi4Upload(StatesGroup):
    wait = State()


def style_kb(prefix):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ib("TNO", f"hoi4:style:{prefix}:tno"),
                ib("TFR", f"hoi4:style:{prefix}:tfr"),
            ],
            [ib("В меню", "menu:home")],
        ]
    )


def mode_kb(prefix, style):
    rows = [
        [ib(label, f"hoi4:mode:{prefix}:{style}:{key}")]
        for key, label in HOI4_MODES.items()
        if key != "news" or style == "tno"
    ]
    rows.append([ib("Другой стиль", f"hoi4:options:{prefix}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def ready_context(scope, state, db, uid):
    if scope.startswith("p"):
        await park_flow(state, uid, db)
    else:
        await state.set_state(NewPage.review)
    await state.update_data(hoi4_upload_scope=None, hoi4_upload_role=None)


async def target_data(scope, state, db, uid):
    if scope == "new":
        return None, {}
    if scope == "d":
        d = await state.get_data()
        if d.get("type") != "superevent":
            return None, None
        return None, d.get("page_data") or {}
    if scope.startswith("p") and scope[1:].isdigit():
        page = await db.get_page(int(scope[1:]), uid)
        if page and page.type == "superevent":
            return page, page.data
    return None, None


async def save_target(scope, state, db, page, data):
    if scope == "d":
        await state.update_data(
            page_data=data,
            preview_path=None,
            theme="tno" if data.get("hoi4_style") == "tno" else "fire_rises",
        )
    else:
        page.data = data
        page.theme = "tno" if data.get("hoi4_style") == "tno" else "fire_rises"
        page.preview_path = None
        await db.update_page(page)


def back_callback(scope):
    return "draft:back" if scope == "d" else f"p:o:{scope[1:]}"


async def show_media(target, state, scope, data):
    await state.set_state(NewPage.review if scope == "d" else None)
    await state.update_data(hoi4_upload_scope=None, hoi4_upload_role=None)
    roles = image_roles(data)
    rows = []
    for key, label in media_roles(data).items():
        row = [
            ib(("✓ " if roles.get(key) else "") + label, f"hoi4:upload:{scope}:{key}")
        ]
        if roles.get(key):
            row.append(ib("Расположение", f"hoi4:crop:{scope}:{key}"))
            rows.append(row)
            row = [ib("Убрать " + label.lower(), f"hoi4:remove:{scope}:{key}")]
        rows.append(row)
    rows.append(
        [ib("Посмотреть карточку", back_callback(scope)), ib("В меню", "menu:home")]
    )
    await flow_show(
        target,
        state,
        "<b>Картинки HOI4</b>\nКаждая картинка идет на свое место. Нажми что хочешь загрузить\nФлаг и значки можно отправить прозрачным PNG",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("hoi4:options:"))
async def options(q, state, db):
    await q.answer()
    scope = q.data.rsplit(":", 1)[1]
    _, data = await target_data(scope, state, db, q.from_user.id)
    if data is None:
        await q.message.answer("Карточка уже закрыта. Открой ее из меню")
        return
    await ready_context(scope, state, db, q.from_user.id)
    await flow_show(
        q, state, "<b>HOI4 Карточка (бета)</b>\nВыбери стиль", style_kb(scope)
    )


@router.callback_query(F.data.startswith("hoi4:style:"))
async def choose_style(q, state, db):
    await q.answer()
    _, _, scope, style = q.data.split(":")
    if style not in ("tno", "tfr"):
        return
    _, data = await target_data(scope, state, db, q.from_user.id)
    if data is None:
        return
    await flow_show(
        q, state, f"<b>{style.upper()}</b>\nЧто собираем?", mode_kb(scope, style)
    )


@router.callback_query(F.data.startswith("hoi4:mode:"))
async def choose_mode(q, state, db):
    await q.answer()
    _, _, scope, style, mode = q.data.split(":")
    if (
        style not in ("tno", "tfr")
        or mode not in HOI4_MODES
        or (mode == "news" and style != "tno")
    ):
        return
    page, data = await target_data(scope, state, db, q.from_user.id)
    if data is None:
        return
    choice = dict(hoi4_style=style, hoi4_mode=mode)
    if scope == "new":
        await state.update_data(hoi4_selection=choice)
        from navigation import method_screen

        await method_screen(q, "superevent")
    else:
        await ready_context(scope, state, db, q.from_user.id)
        data.update(choice)
        await save_target(scope, state, db, page, data)
        await flow_show(
            q,
            state,
            f"Сохранил: {style.upper()} / {HOI4_MODES[mode]}\nДанные и картинки остались",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        ib(
                            "Добавить или править",
                            "draft:fields" if scope == "d" else f"p:e:{page.id}",
                        )
                    ],
                    [
                        ib("Картинки", f"hoi4:media:{scope}"),
                        ib("Посмотреть карточку", back_callback(scope)),
                    ],
                ]
            ),
        )


@router.callback_query(F.data.startswith("hoi4:media:"))
async def media_menu(q, state, db):
    await q.answer()
    scope = q.data.rsplit(":", 1)[1]
    _, data = await target_data(scope, state, db, q.from_user.id)
    if data is None:
        return
    await ready_context(scope, state, db, q.from_user.id)
    await show_media(q, state, scope, data)


@router.callback_query(F.data.startswith("hoi4:upload:"))
async def upload(q, state, db):
    await q.answer()
    _, _, scope, role = q.data.split(":")
    _, data = await target_data(scope, state, db, q.from_user.id)
    if data is None or role not in media_roles(data):
        return
    await ready_context(scope, state, db, q.from_user.id)
    await state.update_data(hoi4_upload_scope=scope, hoi4_upload_role=role)
    await state.set_state(Hoi4Upload.wait)
    await flow_show(
        q,
        state,
        f"<b>{escape(media_roles(data)[role])}</b>\nПришли PNG, JPEG или WEBP. Файл сохранит качество лучше фотографии"
        + (
            "\nЛучше вертикальный портрет по грудь. Впишу целиком, без автоматического обрезания головы"
            if role == "portrait"
            else ""
        ),
        InlineKeyboardMarkup(
            inline_keyboard=[[ib("К картинкам", f"hoi4:media:{scope}")]]
        ),
    )


@router.message(Hoi4Upload.wait, F.photo | F.document)
async def receive_image(msg, state, db, cfg, bot):
    d = await state.get_data()
    scope, role = d.get("hoi4_upload_scope", ""), d.get("hoi4_upload_role", "")
    page, data = await target_data(scope, state, db, msg.from_user.id)
    if data is None or role not in media_roles(data):
        return
    f = msg.photo[-1] if msg.photo else msg.document
    if (f.file_size or 0) > cfg.max_image_mb * 1024 * 1024:
        await msg.answer(f"Файл больше {cfg.max_image_mb} МБ. Пришли картинку поменьше")
        return
    buf = BytesIO()
    try:
        await bot.download(f, destination=buf)
        info = await save_image(
            buf.getvalue(), msg.from_user.id, cfg.work_dir, cfg.max_image_mb
        )
    except BadImage as exc:
        await msg.answer("Картинку не добавил\n" + escape(str(exc)), parse_mode="HTML")
        return
    roles = image_roles(data)
    roles[role] = info.path.name
    data.setdefault("hoi4_crop", {}).pop(role, None)
    data["hoi4_media"] = roles
    set_page_images(data, list(dict.fromkeys(roles.values())))
    await db.add_media(
        msg.from_user.id,
        info.path.name,
        info.width,
        info.height,
        page.id if page else None,
    )
    await save_target(scope, state, db, page, data)
    # Saved-card uploads must not leave an unrelated user's draft in this state.
    await state.set_state(NewPage.review if scope == "d" else None)
    await show_media(msg, state, scope, data)


@router.message(Hoi4Upload.wait, ~F.text.startswith("/"))
async def image_needed(msg):
    await msg.answer("Пришли картинку или вернись к выбору картинок")


@router.callback_query(F.data.startswith("hoi4:remove:"))
async def remove_image(q, state, db):
    await q.answer()
    _, _, scope, role = q.data.split(":")
    page, data = await target_data(scope, state, db, q.from_user.id)
    if data is None:
        return
    roles = image_roles(data)
    roles.pop(role, None)
    data.setdefault("hoi4_crop", {}).pop(role, None)
    data["hoi4_media"] = roles
    set_page_images(data, list(dict.fromkeys(roles.values())))
    await save_target(scope, state, db, page, data)
    await ready_context(scope, state, db, q.from_user.id)
    await show_media(q, state, scope, data)


async def is_hoi4_draft(event, state):
    return (await state.get_data()).get("type") == "superevent"


@router.callback_query(
    F.data.in_({"draft:image", "draft:theme", "quick:theme"}), is_hoi4_draft
)
async def legacy_draft_controls(q, state, db):
    await q.answer()
    _, data = await target_data("d", state, db, q.from_user.id)
    await ready_context("d", state, db, q.from_user.id)
    if q.data == "draft:image":
        await show_media(q, state, "d", data)
    else:
        await flow_show(
            q, state, "<b>HOI4 Карточка (бета)</b>\nВыбери стиль", style_kb("d")
        )


@router.callback_query(F.data.regexp(r"^(pa:\d+:image|p:t:\d+)$"))
async def legacy_page_controls(q, state, db):
    parts = q.data.split(":")
    scope = "p" + (parts[1] if parts[0] == "pa" else parts[2])
    _, data = await target_data(scope, state, db, q.from_user.id)
    if data is None:
        raise SkipHandler
    await q.answer()
    await ready_context(scope, state, db, q.from_user.id)
    if parts[0] == "pa":
        await show_media(q, state, scope, data)
    else:
        await flow_show(
            q, state, "<b>HOI4 Карточка (бета)</b>\nВыбери стиль", style_kb(scope)
        )


def crop_kb(scope, role, data):
    settings = crop_settings(data, role)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ib(
                    ("✓ " if settings["fit"] == "contain" else "") + "Целиком",
                    f"hoi4:adjust:{scope}:{role}:contain",
                ),
                ib(
                    ("✓ " if settings["fit"] == "cover" else "") + "Заполнить окно",
                    f"hoi4:adjust:{scope}:{role}:cover",
                ),
            ],
            [ib("Выше", f"hoi4:adjust:{scope}:{role}:up")],
            [
                ib("Левее", f"hoi4:adjust:{scope}:{role}:left"),
                ib("По центру", f"hoi4:adjust:{scope}:{role}:reset"),
                ib("Правее", f"hoi4:adjust:{scope}:{role}:right"),
            ],
            [ib("Ниже", f"hoi4:adjust:{scope}:{role}:down")],
            [
                ib("Уменьшить", f"hoi4:adjust:{scope}:{role}:out"),
                ib("Увеличить", f"hoi4:adjust:{scope}:{role}:in"),
            ],
            [
                ib("Готово", f"hoi4:media:{scope}"),
                ib("Посмотреть карточку", back_callback(scope)),
            ],
        ]
    )


async def crop_preview(q, state, db, cfg, scope, role, page, data):
    from aiogram.types import FSInputFile, InputMediaPhoto
    from aiogram.exceptions import TelegramBadRequest
    from renderer import render_page
    from models import Page
    from uuid import uuid4
    from media import safe_unlink

    settings = crop_settings(data, role)
    label = media_roles(data)[role]
    sample = Page(
        q.from_user.id,
        "superevent",
        data.get("title") or "HOI4",
        theme="tno" if data.get("hoi4_style") == "tno" else "fire_rises",
        data=dict(data),
    )
    sample.data["hoi4_mode"] = (
        "state"
        if role in ("flag", "portrait", "ideology", "alliance", "focus")
        else "news" if role == "news" else "event"
    )
    path = cfg.work_dir / f"preview_hoi4_crop_{uuid4().hex}.png"
    try:
        await render_page(sample, cfg.work_dir, output=path.name, watermark=False)
        caption = f"{label}\nМасштаб: {settings['zoom']}%\nЦеликом сохраняет всю картинку. Заполнить окно обрезает лишние края"
        markup = crop_kb(scope, role, data)
        if q.message.photo:
            try:
                await q.message.edit_media(
                    InputMediaPhoto(media=FSInputFile(path), caption=caption),
                    reply_markup=markup,
                )
                return
            except TelegramBadRequest:
                pass
        sent = await q.message.answer_photo(
            FSInputFile(path), caption=caption, reply_markup=markup
        )
        if scope == "d":
            from drafts import remember_preview

            await remember_preview(state, sent)
    except ValueError as exc:
        await q.message.answer(
            escape(str(exc)), reply_markup=crop_kb(scope, role, data), parse_mode="HTML"
        )
    finally:
        safe_unlink(path, cfg.work_dir, "preview_")


@router.callback_query(F.data.startswith("hoi4:crop:"))
async def open_crop(q, state, db, cfg):
    await q.answer()
    _, _, scope, role = q.data.split(":")
    page, data = await target_data(scope, state, db, q.from_user.id)
    if data is None or role not in media_roles(data) or not image_roles(data).get(role):
        return
    await ready_context(scope, state, db, q.from_user.id)
    await crop_preview(q, state, db, cfg, scope, role, page, data)


@router.callback_query(F.data.startswith("hoi4:adjust:"))
async def adjust_crop(q, state, db, cfg):
    await q.answer()
    _, _, scope, role, action = q.data.split(":")
    page, data = await target_data(scope, state, db, q.from_user.id)
    if data is None or role not in media_roles(data) or not image_roles(data).get(role):
        return
    values = crop_settings(data, role)
    if action in ("contain", "cover"):
        values.update(fit=action, zoom=100, x=50, y=50)
    elif action == "reset":
        values.update(x=50, y=50, zoom=100)
    elif action in ("left", "right"):
        values["x"] = max(0, min(100, values["x"] + (10 if action == "right" else -10)))
    elif action in ("up", "down"):
        values["y"] = max(0, min(100, values["y"] + (10 if action == "down" else -10)))
    elif action in ("in", "out"):
        values["zoom"] = max(
            100, min(300, values["zoom"] + (10 if action == "in" else -10))
        )
    else:
        return
    data.setdefault("hoi4_crop", {})[role] = values
    await save_target(scope, state, db, page, data)
    await crop_preview(q, state, db, cfg, scope, role, page, data)
