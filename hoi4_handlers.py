"""HOI4 format/style selection and explicitly assigned images."""

from html import escape
from io import BytesIO

from aiogram import F, Router
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup

from drafts import park_flow
from media import BadImage, page_images, save_image, set_page_images
from templates import HOI4_MODES, hoi4_mode
from hoi4_renderer import image_roles, media_roles
from ui import ib, flow_show

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
    roles = image_roles(data)
    rows = []
    for key, label in media_roles(data).items():
        row = [
            ib(("✓ " if roles.get(key) else "") + label, f"hoi4:upload:{scope}:{key}")
        ]
        if roles.get(key):
            row.append(ib("Убрать", f"hoi4:remove:{scope}:{key}"))
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
        return
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
    await show_media(q, state, scope, data)


@router.callback_query(F.data.startswith("hoi4:upload:"))
async def upload(q, state, db):
    await q.answer()
    _, _, scope, role = q.data.split(":")
    _, data = await target_data(scope, state, db, q.from_user.id)
    if data is None or role not in media_roles(data):
        return
    await state.update_data(hoi4_upload_scope=scope, hoi4_upload_role=role)
    await state.set_state(Hoi4Upload.wait)
    await flow_show(
        q,
        state,
        f"<b>{escape(media_roles(data)[role])}</b>\nПришли PNG, JPEG или WEBP. Файл сохранит качество лучше фотографии",
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
    from states import NewPage, EditPage

    await state.set_state(NewPage.review if scope == "d" else EditPage.image)
    await show_media(msg, state, scope, data)


@router.message(Hoi4Upload.wait)
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
    data["hoi4_media"] = roles
    set_page_images(data, list(dict.fromkeys(roles.values())))
    await save_target(scope, state, db, page, data)
    await show_media(q, state, scope, data)
