"""Private admin-only post utility; deliberately absent from public menus."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import LinkPreviewOptions, Message, MessageEntity

from admin import AdminFilter, is_admin
from post_format import MarkupError, parse_post, split_post

router = Router(name="post_format")
_PREVIOUS = "_postformat_previous_state"


class PostFormat(StatesGroup):
    text = State()


def allowed(msg: Message) -> bool:
    return (msg.chat.type == "private" and msg.from_user is not None
            and not msg.from_user.is_bot and is_admin(msg.from_user.id))


async def send_formatted(msg: Message, source: str) -> None:
    # Defense in depth: even direct calls cannot bypass the access check.
    if not allowed(msg):
        return
    try:
        parts = split_post(parse_post(source))
    except MarkupError as exc:
        await msg.answer(f"Ошибка разметки: {exc}", parse_mode=None)
        return
    for part in parts:
        await msg.answer(
            part.text,
            entities=[MessageEntity(type=e.type, offset=e.offset, length=e.length)
                      for e in part.entities],
            parse_mode=None,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )


@router.message(Command("postformat"))
async def postformat(msg: Message, state: FSMContext, command: CommandObject) -> None:
    # Consume unauthorized attempts silently, including attempts from groups.
    if not allowed(msg):
        return
    source = command.args
    if not source and msg.reply_to_message:
        source = msg.reply_to_message.text or msg.reply_to_message.caption
    if source:
        await send_formatted(msg, source)
        return
    previous = await state.get_state()
    if previous != PostFormat.text.state:
        await state.update_data(**{_PREVIOUS: previous})
        await state.set_state(PostFormat.text)
    await msg.answer(
        "Форматирование постов включено\n\n"
        "Пришли текст с разметкой:\n"
        "**жирный**\n__подчеркнутый__\n_курсив_\n"
        "~~зачеркнутый~~\n||спойлер||\n`код`\n\n"
        "Можно совмещать: **__жирный и подчеркнутый__**\n"
        "Для буквального маркера поставь перед ним обратный слеш\n\n"
        "Верну готовое сообщение, его можно переслать в канал\n"
        "Выход: /postformat_off или /cancel",
        parse_mode=None,
    )


@router.message(Command("postformat_off"))
@router.message(PostFormat.text, Command("cancel"))
async def postformat_off(msg: Message, state: FSMContext) -> None:
    if not allowed(msg):
        return
    if await state.get_state() == PostFormat.text.state:
        data = await state.get_data()
        previous = data.pop(_PREVIOUS, None)
        await state.set_data(data)
        await state.set_state(previous)
    await msg.answer("Форматирование постов выключено", parse_mode=None)


@router.message(PostFormat.text, AdminFilter(), F.chat.type == "private",
                F.text, ~F.text.startswith("/"))
async def postformat_text(msg: Message) -> None:
    await send_formatted(msg, msg.text or "")


@router.message(PostFormat.text, AdminFilter(), F.chat.type == "private", ~F.text)
async def postformat_nontext(msg: Message) -> None:
    if allowed(msg):
        await msg.answer("Пришли пост текстом. Выход: /postformat_off", parse_mode=None)
