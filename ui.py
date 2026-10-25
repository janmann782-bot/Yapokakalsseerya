from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from typing import Awaitable, TypeVar

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from models import Page
from locales import tr
from templates import TEMPLATES, Template
from themes import THEMES

CREATE = "Собрать карточку"
MY_PAGES = "Мои карточки"
THEMES_BTN = "Оформление"
SETTINGS = "Настройки"
HELP = "Как пользоваться"
STATS = "Счетчик карточек"
NEWS = "📰 Новость"
SUPEREVENT = "‼️ Суперевент (БЕТА)"
T = TypeVar("T")

# типы с одной картинкой без своих полей
TFR_SIMPLE_TYPES = frozenset({"news", "superevent", "mirotorets"})
SPECIAL_TYPES = frozenset({"news", "superevent", "mirotorets"})
NO_IMAGE_TYPES = frozenset()


def ib(text: str, data: str, **_kwargs) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def home_kb(has_draft: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if has_draft:
        rows.append([ib("Продолжить черновик", "draft:resume")])
    rows += [[ib("Собрать карточку", "nav:create")],
             [ib("Мои карточки", "pages:list"), ib("Настройки", "nav:settings")],
             [ib("Как пользоваться", "nav:help"), ib("Счетчик карточек", "nav:stats")]]
    if has_draft:
        rows.append([ib("Удалить черновик", "draft:discard")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def field_sections_kb(tpl: Template, data: dict, page_id: int | None = None) -> InlineKeyboardMarkup:
    scope = "d" if page_id is None else f"p{page_id}"
    groups = list(dict.fromkeys(f.section for f in tpl.fields))
    rows = []
    for i, group in enumerate(groups):
        fields = [f for f in tpl.fields if f.section == group]
        filled = sum(data.get(f.key) not in (None, "", []) for f in fields)
        rows.append([ib(f"{group} - {filled}/{len(fields)}", f"group:{scope}:g:{i}:0")])
    if data.get("custom_fields"):
        rows.append([ib("Свои поля", f"group:{scope}:c:0:0")])
    for i, sec in enumerate(data.get("sections") or []):
        rows.append([ib(str(sec.get("title", "Свой раздел"))[:45], f"group:{scope}:x:{i}:0")])
    if tpl.key not in TFR_SIMPLE_TYPES:
        rows.append([ib("Добавить поле", "draft:custom" if page_id is None else f"pa:{page_id}:custom"), ib("Добавить раздел", "draft:section" if page_id is None else f"pa:{page_id}:section")])
    rows.append([ib("Посмотреть карточку", "draft:back" if page_id is None else f"p:o:{page_id}"), ib("В меню", "menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def field_group_kb(tpl: Template, data: dict, scope: str, kind: str, index: int, offset: int = 0):
    page_id = None if scope == "d" else int(scope[1:])
    prefix = "df" if page_id is None else f"pe:{page_id}:s"
    rows = []
    if kind == "g":
        group = list(dict.fromkeys(f.section for f in tpl.fields))[index]
        for i, f in enumerate(tpl.fields):
            if f.section == group:
                mark = "✓ " if data.get(f.key) not in (None, "", []) else ""
                rows.append([ib(f"{mark}{f.label}"[:60], f"{prefix}:{i}")])
    elif kind == "c":
        group = "Свои поля"
        for i, field in enumerate(data.get("custom_fields") or []):
            rows.append([ib(str(field.get("name", "Поле"))[:60], f"dc:{i}" if page_id is None else f"pe:{page_id}:c:{i}")])
    elif kind == "x":
        sec = data["sections"][index]
        group = str(sec.get("title", "Свой раздел"))
        if page_id is not None:
            rows.append([ib("Переименовать раздел", f"pe:{page_id}:h:{index}")])
        for i, field in enumerate(sec.get("fields") or []):
            rows.append([ib(str(field.get("name", "Поле"))[:60], f"dx:{index}:{i}" if page_id is None else f"pe:{page_id}:x:{index}:{i}")])
    else:
        raise ValueError("Неизвестный раздел")
    total = len(rows)
    offset = max(0, min(offset, max(0, (total - 1) // 16 * 16)))
    rows = rows[offset:offset + 16]
    nav = []
    for label, target in (("Предыдущие", offset - 16), ("Следующие", offset + 16)):
        if 0 <= target < total:
            nav.append(ib(label, f"group:{scope}:{kind}:{index}:{target}"))
    if nav:
        rows.append(nav)
    rows.append([ib("К разделам", "draft:fields" if page_id is None else f"p:e:{page_id}")])
    return group, InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=CREATE), KeyboardButton(text=MY_PAGES)],
            [KeyboardButton(text=THEMES_BTN), KeyboardButton(text=SETTINGS)],
            [KeyboardButton(text=STATS), KeyboardButton(text=HELP)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Создать карточку или прислать данные текстом",
    )


def types_kb(*, admin: bool = False) -> InlineKeyboardMarkup:
    ordinary = [ib(x.label, f"compose:{x.key}") for x in TEMPLATES.values() if x.key not in SPECIAL_TYPES]
    rows = [ordinary[i:i + 2] for i in range(0, len(ordinary), 2)]
    rows.append([ib("Еще форматы", "compose:more")])
    rows.append([ib("В меню", "menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wizard_kb(can_back: bool = True, can_skip: bool = True) -> InlineKeyboardMarkup:
    row = []
    if can_back:
        row.append(ib("Предыдущий шаг", "wiz:back"))
    if can_skip:
        row.append(ib("Пока пропустить", "wiz:skip"))
    rows = [row] if row else []
    if can_skip:
        rows.append([ib("Дальше заполню сам", "compose:finish")])
    rows.append([ib("Закрыть редактор", "menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def image_kb(count: int = 0, page_type: str = "") -> InlineKeyboardMarkup:
    rows = []
    single = page_type in TFR_SIMPLE_TYPES
    if count:
        rows.append([ib(f"Готово ({count})", "img:done")])
        for i in range(count):
            if single:
                rows.append([ib("Убрать картинку", f"img:rm:{i}")])
            else:
                rows.append(
                    [
                        ib(f"Подпись {i + 1}", f"img:cap:{i}"),
                        ib(f"Убрать картинку {i + 1}", f"img:rm:{i}"),
                    ]
                )
    else:
        rows.append([ib("Пока без картинки" if single else "Пока без картинок", "img:done")])
    rows += [[ib("Назад", "img:back")], [ib("Закрыть редактор", "menu:home")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)




def parliament_assets_kb(flag_set: bool, parties: list[tuple[str, bool]]) -> InlineKeyboardMarkup:
    rows = []
    flag_mark = "✅" if flag_set else "▫️"
    flag_rm = ib("🗑", "pimg:rm:flag") if flag_set else ib("➕", "pimg:flag")
    rows.append([ib(f"{flag_mark} Флаг страны", "pimg:flag"), flag_rm])
    for i, (name, has_logo) in enumerate(parties):
        mark = "✅" if has_logo else "▫️"
        action = ib("🗑", f"pimg:rm:{i}") if has_logo else ib("➕", f"pimg:set:{i}")
        rows.append([ib(f"{mark} {name}"[:52], f"pimg:set:{i}"), action])
    rows.append([ib("Готово", "pimg:done")])
    rows.append([ib("Назад", "img:back")])
    rows.append([ib("Закрыть редактор", "menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
def page_parliament_assets_kb(page_id: int, flag_set: bool, parties: list[tuple[str, bool]]) -> InlineKeyboardMarkup:
    rows = []
    flag_mark = "✅" if flag_set else "▫️"
    flag_row = [ib(f"{flag_mark} Флаг страны", f"ppimg:{page_id}:flag")]
    if flag_set:
        flag_row.append(ib("🗑", f"ppimg:{page_id}:rm:flag"))
    rows.append(flag_row)
    for i, (name, has_logo) in enumerate(parties):
        mark = "✅" if has_logo else "▫️"
        row = [ib(f"{mark} {name}"[:52], f"ppimg:{page_id}:set:{i}")]
        if has_logo:
            row.append(ib("🗑", f"ppimg:{page_id}:rm:{i}"))
        rows.append(row)
    rows.append([ib("Готово", f"ppimg:{page_id}:done")])
    rows.append([ib("К разделам", f"p:e:{page_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def page_image_kb(page_id: int, count: int, page_type: str = "") -> InlineKeyboardMarkup:
    rows = [[ib(f"Готово ({count})", f"pi:{page_id}:done")]]
    single = page_type in TFR_SIMPLE_TYPES
    for i in range(count):
        if single:
            rows.append([ib("Убрать картинку", f"pi:{page_id}:rm:{i}")])
        else:
            rows.append(
                [
                    ib(f"Подпись {i + 1}", f"pi:{page_id}:cap:{i}"),
                    ib(f"Убрать картинку {i + 1}", f"pi:{page_id}:rm:{i}"),
                ]
            )
    rows.append([ib("К карточке", f"p:o:{page_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def image_caption_kb(page_id: int | None = None) -> InlineKeyboardMarkup:
    if page_id is None:
        skip, back = "imgcap:skip", "imgcap:back"
    else:
        skip, back = f"pc:{page_id}:skip", f"pc:{page_id}:back"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("Оставить без подписи", skip)],
            [ib("К картинкам", back)],
            [ib("Закрыть редактор", "menu:home" if page_id is None else f"p:o:{page_id}")],
        ]
    )


def themes_kb(prefix: str, selected: str = "", page_type: str = "") -> InlineKeyboardMarkup:
    from themes import theme_allowed

    rows = []
    for x in THEMES.values():
        if page_type and not theme_allowed(x.key, page_type):
            continue
        mark = "▼ " if x.key == selected else ""
        rows.append([ib(f"{mark}{x.name}", f"{prefix}:{x.key}")])
    rows.append([ib("Назад", f"{prefix}:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def olddoc_options_kb(
    page_id: int | None,
    *,
    stain_count: int = 0,
    paper: int = 0,
    paper_total: int = 6,
    drunk: bool = False,
    drunk_flags: bool = False,
    substances: bool = False,
    window: bool = True,
    outline: bool = True,
    bw: bool = False,
) -> InlineKeyboardMarkup:
    paper_n = (paper % max(1, paper_total)) + 1
    text_label = f"Текст: {'пьяный' if drunk else 'обычный'}"
    flags_label = f"Флаги: {'пьяные' if drunk_flags else 'обычные'}"
    sub_label = f"Под веществами: {'вкл' if substances else 'выкл'}"
    win_label = f"Окно: {'вкл' if window else 'выкл'}"
    out_label = f"Обводка: {'вкл' if outline else 'выкл'}"
    bw_label = f"Черно-белый: {'вкл' if bw else 'выкл'}"
    if page_id is None:
        pfx = "old"
        back = "draft:back"
        back_label = "Посмотреть карточку"
        apply = "old:apply"
    else:
        pfx = f"old:{page_id}"
        back = f"p:o:{page_id}"
        back_label = "К карточке"
        apply = f"old:{page_id}:apply"
    rows = [
        [ib("Другой вариант", f"{pfx}:reseed")],
        [
            ib("◀️", f"{pfx}:paper_prev"),
            ib(f"Бумага: {paper_n}/{paper_total}", f"{pfx}:paper"),
            ib("▶️", f"{pfx}:paper_next"),
        ],
        [
            ib("◀️", f"{pfx}:cups_prev"),
            ib(f"Пятна: {stain_count}", f"{pfx}:cups"),
            ib("▶️", f"{pfx}:cups_next"),
        ],
        [ib(text_label, f"{pfx}:text"), ib(flags_label, f"{pfx}:flags")],
        [ib(sub_label, f"{pfx}:sub")],
        [ib(win_label, f"{pfx}:window"), ib(out_label, f"{pfx}:outline")],
        [ib(bw_label, f"{pfx}:bw")],
        [ib("Применить", apply)],
        [ib(back_label, back)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def draft_kb(page_type: str | None = None, theme: str = "") -> InlineKeyboardMarkup:
    rows = [[ib("Сохранить карточку", "draft:save")],
            [ib("Добавить или править", "draft:fields")],
            [ib("Картинки", "draft:image"), ib("Оформление", "draft:theme")],
            [ib("Скачать PNG", "draft:export"), ib("Забрать текст", "draft:text")]]
    if page_type == "battle":
        rows.insert(3, [ib("Стороны и участники", "draft:sides")])
    if theme == "olddoc":
        rows.insert(3, [ib("Бумага и эффекты", "draft:olddoc")])
    rows.append([ib("Закрыть редактор", "menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quick_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [ib("Посмотреть карточку", "quick:preview")],
        [ib("Разобрать по разделам", "quick:fields"), ib("Оформление", "quick:theme")],
        [ib("Забрать текст", "quick:text"), ib("Закрыть редактор", "menu:home")],
    ])


def fields_kb(tpl: Template, data: dict, page_id: int | None = None, offset: int = 0) -> InlineKeyboardMarkup:
    rows = []
    btns = []
    for i, f in enumerate(tpl.fields):
        mark = "✓ " if data.get(f.key) not in (None, "", []) else ""
        cb = f"df:{i}" if page_id is None else f"pe:{page_id}:s:{i}"
        btns.append(ib(f"{mark}{f.label}"[:32], cb))
        if len(btns) == 2:
            rows.append(btns)
            btns = []
    if btns:
        rows.append(btns)

    for i, x in enumerate(data.get("custom_fields") or []):
        name = str(x.get("name", "Свое поле"))[:27]
        cb = f"dc:{i}" if page_id is None else f"pe:{page_id}:c:{i}"
        rows.append([ib(f"✓ ✦ {name}", cb)])

    for i, sec in enumerate(data.get("sections") or []):
        title = str(sec.get("title", "Раздел"))[:25]
        if page_id is not None:
            rows.append([ib(f"🧩 {title}", f"pe:{page_id}:h:{i}")])
        for j, x in enumerate(sec.get("fields") or []):
            name = str(x.get("name", "Поле"))[:25]
            cb = f"dx:{i}:{j}" if page_id is None else f"pe:{page_id}:x:{i}:{j}"
            rows.append([ib(f"↳ ✓ {name}", cb)])

    # Keep Telegram keyboards below 100 buttons, including custom sections.
    page_size = 30
    total = len(rows)
    offset = max(0, min(offset, max(0, (total - 1) // page_size * page_size)))
    rows = rows[offset:offset + page_size]
    prefix = "fields:d" if page_id is None else f"fields:p:{page_id}"
    nav = []
    if offset:
        nav.append(ib("Предыдущие поля", f"{prefix}:{offset - page_size}"))
    if offset + page_size < total:
        nav.append(ib("Следующие поля", f"{prefix}:{offset + page_size}"))
    if nav:
        rows.append(nav)
    is_news = tpl.key in TFR_SIMPLE_TYPES
    if page_id is None:
        extra = []
        if not is_news:
            extra.append([ib("Добавить поле", "draft:custom"), ib("Добавить раздел", "draft:section")])
        if tpl.key not in NO_IMAGE_TYPES:
            if tpl.key == "parliament":
                extra.append([ib("Флаг и логотипы", "draft:image")])
            else:
                extra.append([ib("Картинка" if is_news else "Картинки", "draft:image")])
        extra.append([ib("Посмотреть карточку", "draft:back")])
        rows += extra
    else:
        extra = []
        if not is_news:
            extra.append([ib("Добавить поле", f"pa:{page_id}:custom"), ib("Добавить раздел", f"pa:{page_id}:section")])
        if tpl.key not in NO_IMAGE_TYPES:
            if tpl.key == "parliament":
                extra.append([ib("Флаг и логотипы", f"pa:{page_id}:image")])
            else:
                extra.append([ib("Картинка" if is_news else "Картинки", f"pa:{page_id}:image")])
        extra.append([ib("К карточке", f"p:o:{page_id}")])
        rows += extra
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_value_kb(back: str, cancel: str = "menu:home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("Назад", back)],
            [ib("Закрыть редактор", cancel)],
        ]
    )


def page_actions_kb(page_id: int, page_type: str | None = None, theme: str = "") -> InlineKeyboardMarkup:
    rows = [[ib("Добавить или править", f"p:e:{page_id}")],
            [ib("Картинки", f"pa:{page_id}:image"), ib("Оформление", f"p:t:{page_id}")],
            [ib("Скачать PNG", f"p:x:{page_id}"), ib("Забрать текст", f"p:txt:{page_id}")],
            [ib("Сделать копию", f"p:c:{page_id}"), ib("Удалить карточку", f"p:d:{page_id}")]]
    if page_type == "battle":
        rows.insert(2, [ib("Стороны и участники", f"p:bs:{page_id}")])
    if theme == "olddoc":
        rows.insert(2, [ib("Бумага и эффекты", f"p:old:{page_id}")])
    rows.append([ib("К моим карточкам", "pages:list"), ib("В меню", "menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def battle_sides_kb(prefix: str, page_id: int | None = None) -> InlineKeyboardMarkup:
    base = f"bs:{'p:' + str(page_id) if page_id is not None else 'd'}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("◀️ Сторона 1", f"{base}:0"), ib("Сторона 2 ▶️", f"{base}:1")],
            [ib("Назад", f"{base}:back")],
        ]
    )


def battle_side_edit_kb(prefix: str, side_i: int, members: list[dict], page_id: int | None = None) -> InlineKeyboardMarkup:
    base = f"bs:{'p:' + str(page_id) if page_id is not None else 'd'}"
    rows = []
    for i, m in enumerate(members):
        name = str(m.get("name") or "Участник")[:22]
        flag = "🚩" if m.get("flag") else "▫️"
        rows.append([
            ib(f"{flag} {name}", f"{base}:{side_i}:e:{i}"),
            ib("🗑", f"{base}:{side_i}:r:{i}"),
        ])
    if len(members) < 10:
        rows.append([ib("Добавить участника", f"{base}:{side_i}:add")])
    rows.append([ib("Переименовать сторону", f"{base}:{side_i}:name")])
    rows.append([ib("К сторонам", f"{base}:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def battle_member_kb(prefix: str, side_i: int, member_i: int, page_id: int | None = None) -> InlineKeyboardMarkup:
    base = f"bs:{'p:' + str(page_id) if page_id is not None else 'd'}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("Изменить имя", f"{base}:{side_i}:name:{member_i}"), ib("Поменять флаг", f"{base}:{side_i}:flag:{member_i}")],
            [ib("Удалить", f"{base}:{side_i}:r:{member_i}")],
            [ib("К участникам", f"{base}:{side_i}")],
        ]
    )


def pages_kb(pages: list[Page], offset: int = 0, has_more: bool = False) -> InlineKeyboardMarkup:
    rows = [[ib(p.title[:55], f"p:o:{p.id}")] for p in pages[:8]]
    nav = []
    if offset:
        nav.append(ib("Предыдущие", f"cards:{max(0, offset - 8)}"))
    if has_more:
        nav.append(ib("Следующие", f"cards:{offset + 8}"))
    if nav:
        rows.append(nav)
    rows += [[ib("Найти по названию", "cards:search"), ib("Собрать еще", "nav:create")], [ib("В меню", "menu:home")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_kb(page_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ib("Да, удалить карточку", f"pd:{page_id}:yes")],
            [ib("Оставить карточку", f"p:o:{page_id}")],
        ]
    )


def settings_kb(watermark: bool | None = None) -> InlineKeyboardMarkup:
    mark = "включена" if watermark else "выключена"
    return InlineKeyboardMarkup(inline_keyboard=[
        [ib("Тема новых карточек", "settings:theme")],
        [ib("Шрифт", "settings:font"), ib("Размер PNG", "settings:quality")],
        [ib(f"Подпись бота: {mark}", "settings:watermark")],
        [ib("В меню", "menu:home")],
    ])


def fonts_kb(
    choices: list[tuple[str, str]],
    selected: str,
    page: int = 0,
    per_page: int = 8,
    offset: int = 0,
) -> InlineKeyboardMarkup:
    """choices = [(key, label), ...]; offset - стартовый номер (для поиска)."""
    total = max(1, (len(choices) + per_page - 1) // per_page)
    page = max(0, min(page, total - 1))
    chunk = choices[page * per_page : (page + 1) * per_page]
    rows = []
    for i, (key, label) in enumerate(chunk):
        num = offset + page * per_page + i + 1
        mark = "▼ " if key == selected else ""
        rows.append([ib(f"{mark}{num}. {label}"[:40], f"font:set:{key}")])
    nav = []
    if page > 0:
        nav.append(ib("⬅️", f"font:page:{page - 1}"))
    nav.append(ib(f"{page + 1}/{total}", "font:noop"))
    if page + 1 < total:
        nav.append(ib("➡️", f"font:page:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([ib("Найти шрифт", "font:search")])
    rows.append([ib("Загрузить свой шрифт", "font:upload")])
    rows.append([ib("Назад", "settings:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quality_kb(selected: str) -> InlineKeyboardMarkup:
    names = {"standard": "Обычное", "high": "Высокое", "ultra": "Очень высокое"}
    rows = [
        [ib(("▼ " if k == selected else "") + v, f"quality:{k}")]
        for k, v in names.items()
    ]
    rows.append([ib("Назад", "settings:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def progress_text(percent: int) -> str:
    n = min(100, max(0, percent))
    filled = min(10, max(1, round(n / 10))) if n else 0
    bar = "▓" * filled + "░" * (10 - filled)
    return tr("rendering", bar=bar, percent=n)


async def render_progress(msg: Message, job: Awaitable[T]) -> T:
    task = asyncio.create_task(job)
    for n in (18, 31, 47, 64, 78, 89, 96):
        try:
            res = await asyncio.wait_for(asyncio.shield(task), timeout=0.7)
            with suppress(TelegramBadRequest):
                await msg.edit_text(progress_text(100))
            return res
        except TimeoutError:
            with suppress(TelegramBadRequest):
                await msg.edit_text(progress_text(n))

    res = await task
    with suppress(TelegramBadRequest):
        await msg.edit_text(progress_text(100))
    return res


async def send_png(
    msg: Message,
    path: str | Path,
    caption: str,
    markup: InlineKeyboardMarkup | None = None,
    document: bool = False,
) -> Message:
    f = FSInputFile(path)
    if document:
        return await msg.answer_document(f, caption=caption[:1024], reply_markup=markup)
    try:
        return await msg.answer_photo(f, caption=caption[:1024], reply_markup=markup)
    except TelegramBadRequest:
        return await msg.answer_document(
            FSInputFile(path), caption=caption[:1024], reply_markup=markup
        )


DIV = "---------------"


def box(text: str) -> str:
    """Рамка-разделитель вокруг блока текста."""
    body = (text or "").strip()
    return f"{DIV}\n{body}\n{DIV}"


def quote(text: str) -> str:
    """Цитата (HTML blockquote)."""
    body = (text or "").strip()
    if not body:
        return ""
    # экранируем только если вызывающий не прислал готовый HTML
    return f"<blockquote>{body}</blockquote>"


async def flow_show(target, state, text: str, reply_markup=None, parse_mode="HTML", *, as_new=False):
    """Update the editor screen; send a new message only for media or expired screens."""
    is_callback = hasattr(target, "message")
    msg = target.message if is_callback else target
    data = await state.get_data()
    sent = None
    try:
        if not as_new and is_callback and getattr(msg, "text", None) and callable(getattr(msg, "edit_text", None)):
            sent = await msg.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        elif not as_new and data.get("flow_message_id") and data.get("flow_chat_id") and callable(getattr(msg.bot, "edit_message_text", None)):
            sent = await msg.bot.edit_message_text(text, chat_id=data["flow_chat_id"], message_id=data["flow_message_id"], reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return msg
    if sent is None:
        sent = await msg.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
    await state.update_data(flow_message_id=sent.message_id, flow_chat_id=sent.chat.id)
    return sent
