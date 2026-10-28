from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update, User

from post_format import FormattedPost, MarkupError, Span, parse_post, split_post, utf16_len
from post_format_handlers import PostFormat, postformat, postformat_off, send_formatted


class FormattingTests(unittest.TestCase):
    def test_bold_underline_nested_and_emoji_offsets(self):
        post = parse_post("😀 **Заголовок __важно__**")
        self.assertEqual(post.text, "😀 Заголовок важно")
        self.assertEqual(post.entities, (Span("bold", 3, 15), Span("underline", 13, 5)))

    def test_every_style(self):
        post = parse_post("**б** __п__ _к_ ~~з~~ ||с|| `код`")
        self.assertEqual(post.text, "б п к з с код")
        self.assertEqual([e.type for e in post.entities],
                         ["bold", "underline", "italic", "strikethrough", "spoiler", "code"])

    def test_html_is_literal_and_hashtags_survive(self):
        text = '<b>Без исполнения</b> & 2 < 3 #Аурелия_Лор https://a.test/some_path'
        self.assertEqual(parse_post(text), FormattedPost(text, ()))

    def test_escaped_markers(self):
        post = parse_post(r"\*\*буквально\*\* \_\_тоже\_\_")
        self.assertEqual(post.text, "**буквально** __тоже__")
        self.assertFalse(post.entities)

    def test_code_does_not_parse_markers(self):
        post = parse_post('`**пример** __код__`')
        self.assertEqual(post.text, '**пример** __код__')
        self.assertEqual(post.entities[0].type, "code")

    def test_fenced_code(self):
        post = parse_post('```text\n**пример**\n```')
        self.assertEqual(post.text, '**пример**\n')
        self.assertEqual(post.entities[0].type, "pre")

    def test_bad_markup_does_not_silently_change_text(self):
        for text in ('**не закрыт', '__тоже', '`код', '**__крест**__', '**`код`**', '   ', '****'):
            with self.subTest(text=text), self.assertRaises(MarkupError):
                parse_post(text)

    def test_splitting_preserves_text_and_spanning_entities(self):
        post = parse_post('**' + '😀А' * 2000 + '**')
        parts = split_post(post)
        self.assertEqual(''.join(p.text for p in parts), post.text)
        self.assertEqual(len(parts), 2)
        for part in parts:
            self.assertLessEqual(utf16_len(part.text), 4096)
            self.assertEqual(part.entities, (Span('bold', 0, utf16_len(part.text)),))

    def test_split_at_newline_preserves_whitespace(self):
        text = 'a' * 3000 + '\n\n' + 'b' * 2000
        parts = split_post(parse_post(text))
        self.assertEqual(''.join(p.text for p in parts), text)
        self.assertTrue(parts[0].text.endswith('\n\n'))

    def test_split_entities_with_partial_and_absent_overlap(self):
        post = parse_post('АА**ББББ**ВВ')
        self.assertEqual(split_post(post, limit=4), [
            FormattedPost('ААББ', (Span('bold', 2, 2),)),
            FormattedPost('ББВВ', (Span('bold', 0, 2),)),
        ])

    def test_entity_limit_is_checked_before_sending(self):
        with self.assertRaises(MarkupError):
            split_post(parse_post(' '.join(['**x**'] * 101)))


def message(uid=7787565361, text='/postformat', chat_type='private', **extra):
    return Message(message_id=1, date=datetime.now(timezone.utc),
                   chat=Chat(id=uid if chat_type == 'private' else -1001234, type=chat_type),
                   from_user=User(id=uid, is_bot=False, first_name='Test'), text=text, **extra)


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.storage = MemoryStorage()
        self.state = FSMContext(self.storage, StorageKey(bot_id=123456, chat_id=7787565361, user_id=7787565361))

    async def test_mode_restores_existing_flow_and_data(self):
        await self.state.set_state('NewPage:field')
        await self.state.set_data({'page_data': {'title': 'Черновик'}})
        msg = SimpleNamespace(chat=SimpleNamespace(type='private'),
                              from_user=SimpleNamespace(id=7787565361, is_bot=False),
                              reply_to_message=None, answer=AsyncMock())
        await postformat(msg, self.state, CommandObject(command='postformat'))
        await postformat(msg, self.state, CommandObject(command='postformat'))
        self.assertEqual(await self.state.get_state(), PostFormat.text.state)
        await postformat_off(msg, self.state)
        self.assertEqual(await self.state.get_state(), 'NewPage:field')
        self.assertEqual(await self.state.get_data(), {'page_data': {'title': 'Черновик'}})

    async def test_direct_call_cannot_bypass_access_control(self):
        for uid, kind in [(42, 'private'), (7787565361, 'group')]:
            msg = SimpleNamespace(chat=SimpleNamespace(type=kind),
                                  from_user=SimpleNamespace(id=uid, is_bot=False), answer=AsyncMock())
            await send_formatted(msg, '**secret**')
            await postformat(msg, self.state, CommandObject(command='postformat'))
            await postformat_off(msg, self.state)
            msg.answer.assert_not_awaited()
        self.assertIsNone(await self.state.get_state())

    async def test_reply_and_direct_commands_are_one_shot(self):
        reply = SimpleNamespace(text='**Ответ**', caption=None)
        msg = SimpleNamespace(chat=SimpleNamespace(type='private'),
                              from_user=SimpleNamespace(id=7787565361, is_bot=False),
                              reply_to_message=reply, answer=AsyncMock())
        await postformat(msg, self.state, CommandObject(command='postformat'))
        msg.answer.assert_awaited_once()
        args, kwargs = msg.answer.await_args
        self.assertEqual(args[0], 'Ответ')
        self.assertEqual(kwargs['entities'][0].type, 'bold')
        self.assertIsNone(kwargs['parse_mode'])
        self.assertIsNone(await self.state.get_state())
        await postformat(msg, self.state, CommandObject(command='postformat', args='__текст__'))
        self.assertEqual(msg.answer.await_args.kwargs['entities'][0].type, 'underline')

    async def test_invalid_input_gets_error_instead_of_partial_post(self):
        msg = SimpleNamespace(chat=SimpleNamespace(type='private'),
                              from_user=SimpleNamespace(id=7787565361, is_bot=False), answer=AsyncMock())
        await send_formatted(msg, '**не закрыт')
        self.assertTrue(msg.answer.await_args.args[0].startswith('Ошибка разметки:'))
        self.assertEqual(msg.answer.await_count, 1)


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        if not isinstance(method, SendMessage):
            raise AssertionError(f'Unexpected Telegram request: {type(method).__name__}')
        self.sent.append(method)
        return Message(message_id=len(self.sent), date=datetime.now(timezone.utc),
                       chat=Chat(id=method.chat_id, type='private'), text=method.text)

    async def stream_content(self, url, **kwargs):
        yield b''


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_dispatch_auth_state_and_command_routing(self):
        session = RecordingSession()
        bot = Bot('123456:TEST_TOKEN_FOR_LOCAL_TEST_ONLY', session=session)
        dp = Dispatcher(storage=MemoryStorage())
        # Load a fresh router: the full bot suite may already own the application router.
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location("post_format_dispatch_test",
                                                    Path(__file__).with_name("post_format_handlers.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        dp.include_router(module.router)
        public = Router()

        @public.message()
        async def fallback(msg: Message):
            await msg.answer('PUBLIC')

        dp.include_router(public)
        serial = 0

        async def feed(msg):
            nonlocal serial
            serial += 1
            await dp.feed_update(bot, Update(update_id=serial, message=msg))

        # Neither a guessed command nor group-admin status grants access.
        await feed(message(42))
        await feed(message(7787565361, chat_type='supergroup'))
        await feed(message(42, text='/postformat_off'))
        self.assertEqual(session.sent, [])
        await feed(message())
        self.assertIn('Форматирование', session.sent[-1].text)
        await feed(message(text='😀 **жирный __и подчеркнутый__**'))
        self.assertEqual(session.sent[-1].text, '😀 жирный и подчеркнутый')
        self.assertEqual({e.type for e in session.sent[-1].entities}, {'bold', 'underline'})
        # A copied/forged FSM state still does not bypass the sender filter.
        forged = dp.fsm.get_context(bot=bot, chat_id=42, user_id=42)
        await forged.set_state(PostFormat.text)
        await feed(message(42, text='**secret**'))
        self.assertEqual(session.sent[-1].text, 'PUBLIC')
        await feed(message(text='/cancel'))
        self.assertEqual(session.sent[-1].text, 'Форматирование постов выключено')
        await feed(message(text='ordinary'))
        self.assertEqual(session.sent[-1].text, 'PUBLIC')
        await bot.session.close()
        await dp.storage.close()


if __name__ == '__main__':
    unittest.main()
