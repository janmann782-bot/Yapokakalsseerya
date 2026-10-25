from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, UTC
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, DeleteMessage, EditMessageText, GetFile, SendMessage, SendPhoto, SendDocument
from aiogram.types import Message, User, Chat, CallbackQuery, Update, File, Document
from PIL import Image

from bot import make_dispatcher
from config import Config
from db import Db
from models import Page
from states import NewPage, Navigation, FontSearch
from locales import RU, tr
from ui import field_sections_kb, field_group_kb, home_kb, types_kb
from templates import TEMPLATES


class LocalTelegram(BaseSession):
    """Records Telegram methods locally. No HTTP requests or real messages."""
    def __init__(self):
        super().__init__()
        self.calls = []
        self.download = b""

    async def close(self):
        pass

    async def stream_content(self, url, **kwargs):
        yield self.download

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (AnswerCallbackQuery, DeleteMessage)):
            return True
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="test", file_path="local/file")
        if isinstance(method, (SendMessage, EditMessageText, SendPhoto, SendDocument)):
            return Message(message_id=getattr(method, "message_id", None) or len(self.calls) + 10,
                           date=datetime.now(UTC), chat=Chat(id=int(method.chat_id), type="private"),
                           from_user=User(id=bot.id, is_bot=True, first_name="InfoBox"),
                           text=getattr(method, "text", None), caption=getattr(method, "caption", None))
        raise AssertionError(f"Unexpected Telegram method: {method}")


class NavigationTests(unittest.IsolatedAsyncioTestCase):
    next_user = 100
    dispatcher = None

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = Db(self.root / "test.db")
        await self.db.init()
        self.cfg = Config("123456:TEST", self.root, self.root / "test.db")
        if self.__class__.dispatcher is None:
            self.__class__.dispatcher = make_dispatcher(self.db, self.cfg)
        self.dp = self.__class__.dispatcher
        self.dp["db"], self.dp["cfg"] = self.db, self.cfg
        self.session = LocalTelegram()
        self.bot = Bot("123456:TEST", session=self.session)
        self.__class__.next_user += 1
        self.uid = self.__class__.next_user
        self.state = self.dp.fsm.get_context(bot=self.bot, chat_id=self.uid, user_id=self.uid)
        self.updates = 0
        self.stack = ExitStack()
        for path in ("handlers.spawn_user_start", "create_handlers.spawn_create_started", "create_handlers.spawn_page_saved", "log_sink.spawn_created_page_log"):
            self.stack.enter_context(patch(path))

    async def asyncTearDown(self):
        self.stack.close()
        await self.bot.session.close()
        self.temp.cleanup()

    async def message(self, text=None, document=None):
        self.updates += 1
        msg = Message(message_id=self.updates, date=datetime.now(UTC), chat=Chat(id=self.uid, type="private"), from_user=User(id=self.uid, is_bot=False, first_name="Тест"), text=text, document=document)
        await self.dp.feed_update(self.bot, Update(update_id=self.updates, message=msg))

    async def callback(self, data):
        self.updates += 1
        msg = Message(message_id=10, date=datetime.now(UTC), chat=Chat(id=self.uid, type="private"), from_user=User(id=self.bot.id, is_bot=True, first_name="InfoBox"), text="Экран")
        q = CallbackQuery(id=str(self.updates), from_user=User(id=self.uid, is_bot=False, first_name="Тест"), chat_instance="test", message=msg, data=data)
        await self.dp.feed_update(self.bot, Update(update_id=self.updates, callback_query=q))

    async def test_channel_recommendations_once_across_restarts(self):
        # Existing users also see the notice once after upgrading.
        await self.db.touch_user(self.uid)
        await self.message("/start")
        notices = [c for c in self.session.calls if isinstance(c, SendMessage) and "Рекомендуем подписаться" in c.text]
        self.assertEqual(len(notices), 1)
        self.assertIn("(необязательно)", notices[0].text)
        self.assertIn("@Aurelia_Infobox", notices[0].text)
        self.assertIn("@AureliaAOH2", notices[0].text)
        self.assertTrue(await self.db.channels_recommended(self.uid))
        self.dp["db"] = self.db = Db(self.root / "test.db")
        await self.db.init()
        await self.state.clear()
        await self.message("/start")
        notices = [c for c in self.session.calls if isinstance(c, SendMessage) and "Рекомендуем подписаться" in c.text]
        self.assertEqual(len(notices), 1)
        await self.callback("compose:country")
        await self.callback("build:country:editor")
        await self.message("Кефирстан")
        self.assertEqual(await self.state.get_state(), NewPage.review.state)

    async def test_editor_draft_survives_home_and_fsm_restart(self):
        await self.message("/start")
        await self.callback("compose:country")
        await self.callback("build:country:editor")
        await self.message("Кефирстан")
        self.assertEqual(await self.state.get_state(), NewPage.review.state)
        await self.callback("df:7")  # Capital field, following the real template.
        # Use the template index rather than assuming which fields are present.
        index = next(i for i, f in enumerate(TEMPLATES["country"].fields) if f.key == "capital")
        await self.callback(f"df:{index}")
        await self.message('Город "Ёлки" - <центр>')
        self.assertFalse(any(isinstance(c, SendPhoto) for c in self.session.calls))
        await self.callback("menu:home")
        self.assertIsNone(await self.state.get_state())
        # Reopen the SQLite DB and empty volatile FSM, as after a restart.
        self.dp["db"] = self.db = Db(self.root / "test.db")
        await self.state.clear()
        await self.callback("draft:resume")
        data = await self.state.get_data()
        self.assertEqual(data["page_data"]["capital"], 'Город "Ёлки" - <центр>')
        self.assertTrue(any(isinstance(c, EditMessageText) for c in self.session.calls))

    async def test_new_card_requires_explicit_draft_replacement(self):
        await self.db.save_draft(self.uid, {"type": "country", "page_data": {"title": "Старый"}, "theme": "light"})
        await self.callback("build:person:editor")
        self.assertEqual((await self.db.get_draft(self.uid))["page_data"]["title"], "Старый")
        await self.callback("replace:person:editor")
        self.assertIsNone(await self.db.get_draft(self.uid))
        self.assertEqual((await self.state.get_data())["type"], "person")

    async def test_paste_and_save_clear_only_the_owned_draft(self):
        await self.db.save_draft(self.uid + 1, {"type": "country", "page_data": {"title": "Чужой"}})
        await self.callback("build:country:paste")
        await self.message("Название: Кефирстан\nСтолица: Каменный Мост")
        self.assertEqual(await self.state.get_state(), NewPage.quick.state)
        await self.callback("draft:save")
        self.assertIsNone(await self.db.get_draft(self.uid))
        self.assertIsNotNone(await self.db.get_draft(self.uid + 1))
        self.assertEqual(len(await self.db.get_user_pages(self.uid)), 1)
        await self.callback("draft:save")
        self.assertEqual(len(await self.db.get_user_pages(self.uid)), 1)

    async def test_cyrillic_search_pagination_and_ownership(self):
        for i in range(12):
            await self.db.save_page(Page(self.uid, "country", f"Кефирстан {i}"))
        await self.db.save_page(Page(self.uid + 1, "country", "Кефирстан чужой"))
        await self.callback("cards:search")
        await self.message("кЕфИрСтАн")
        result = [c for c in self.session.calls if isinstance(c, SendMessage)][-1]
        buttons = [b for row in result.reply_markup.inline_keyboard for b in row]
        self.assertEqual(sum(b.callback_data.startswith("p:o:") for b in buttons), 8)
        self.assertIn("cards:8", {b.callback_data for b in buttons})
        await self.callback("cards:8")
        self.assertEqual((await self.state.get_data())["card_query"], "кЕфИрСтАн")
        rows = await self.db.search_pages(self.uid, "КЕФИРСТАН", 8)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(p.owner_id == self.uid for p in rows))

    async def test_document_image_reaches_creation_not_font_upload(self):
        await self.state.set_state(NewPage.image)
        await self.state.set_data({"type": "country", "page_data": {"title": "Кефирстан"}, "image_mode": "initial"})
        buf = BytesIO()
        Image.new("RGB", (100, 80), "blue").save(buf, "PNG")
        self.session.download = buf.getvalue()
        doc = Document(file_id="image", file_unique_id="image", file_name="flag.png", mime_type="image/png", file_size=len(self.session.download))
        await self.message(document=doc)
        draft = await self.db.get_draft(self.uid)
        self.assertEqual(len(draft["page_data"]["images"]), 1)
        self.assertEqual(await self.state.get_state(), NewPage.image_caption.state)

    async def test_section_buttons_cannot_open_other_users_card(self):
        page = await self.db.save_page(Page(self.uid + 1, "country", "Чужая"))
        await self.callback(f"group:p{page.id}:g:0:0")
        texts = [getattr(c, "text", "") for c in self.session.calls]
        self.assertTrue(any("другому человеку" in text for text in texts if text))

    async def test_font_search_retries_and_returns_to_settings(self):
        preview = self.root / "preview_cached.png"
        preview.write_bytes(b"cached")
        page = await self.db.save_page(Page(self.uid, "country", "Кефирстан", preview_path=preview.name))
        await self.callback("font:search")
        await self.message("такогошрифтаужточнонет")
        self.assertEqual(await self.state.get_state(), FontSearch.wait.state)
        await self.message("roboto")
        self.assertIsNone(await self.state.get_state())
        self.assertTrue((await self.state.get_data())["font_search_results"])
        await self.callback("font:set:roboto")
        self.assertEqual((await self.db.get_settings(self.uid)).font, "roboto")
        self.assertIsNone((await self.db.get_page(page.id, self.uid)).preview_path)
        self.assertFalse(preview.exists())

    async def test_battle_flag_skip_and_back_keep_the_draft(self):
        from unittest.mock import AsyncMock
        await self.state.set_data({"type": "battle", "theme": "light", "page_data": {"title": "Битва", "side_1": "Кефирстан"}, "battle_side_i": 0, "battle_member_i": 0, "battle_action": "add_member"})
        await self.state.set_state(NewPage.battle_flag)
        with patch("create_handlers.show_preview", AsyncMock()):
            await self.callback("bs:d:skip")
        self.assertEqual((await self.state.get_data())["type"], "battle")
        await self.callback("bs:d:cancel")
        self.assertEqual(await self.state.get_state(), NewPage.review.state)
        self.assertIsNotNone(await self.db.get_draft(self.uid))


class InterfaceCopyTests(unittest.TestCase):
    def test_vox_copy_preserves_user_values(self):
        forbidden = set("ёЁ—–«»“”‘’")
        for key, text in RU.items():
            self.assertFalse(forbidden.intersection(text), key)
        user_value = 'Ёлки «чужая цитата» & <tag>'
        rendered = tr("saved", title=user_value)
        self.assertIn("Ёлки «чужая цитата» &amp; &lt;tag&gt;", rendered)
        self.assertIn("3 800", tr("too_long", limit=3800))

    def test_each_template_has_reachable_sections(self):
        for tpl in TEMPLATES.values():
            markup = field_sections_kb(tpl, {})
            callbacks = [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data.startswith("group:")]
            fields = set()
            for callback in callbacks:
                _, scope, kind, index, offset = callback.split(":")
                _, kb = field_group_kb(tpl, {}, scope, kind, int(index), int(offset))
                fields.update(b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data.startswith("df:"))
            self.assertEqual(len(fields), len(tpl.fields), tpl.key)
