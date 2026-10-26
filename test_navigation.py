from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, UTC
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, DeleteMessage, EditMessageText, GetFile, SendMessage, SendPhoto, SendDocument, EditMessageMedia, EditMessageReplyMarkup
from aiogram.types import Message, User, Chat, CallbackQuery, Update, File, Document, PhotoSize
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
        self.messages = {}
        self.next_message_id=1000
        self.reject_photos=False

    async def close(self):
        pass

    async def stream_content(self, url, **kwargs):
        yield self.download

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if self.reject_photos and isinstance(method,SendPhoto):
            raise TelegramBadRequest(method=method,message="Bad Request: photo is invalid")
        if isinstance(method, (AnswerCallbackQuery, DeleteMessage)):
            return True
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="test", file_path="local/file")
        if isinstance(method, EditMessageReplyMarkup):
            key=(int(method.chat_id),method.message_id)
            old=self.messages.get(key)
            if old is None:
                old=Message(message_id=method.message_id,date=datetime.now(UTC),chat=Chat(id=int(method.chat_id),type="private"))
            updated=old.model_copy(update={"reply_markup":method.reply_markup}).as_(bot)
            self.messages[key]=updated
            return updated
        if isinstance(method, EditMessageMedia):
            msg=Message(message_id=method.message_id or 10,date=datetime.now(UTC),chat=Chat(id=int(method.chat_id),type="private"),photo=[PhotoSize(file_id="preview",file_unique_id="preview",width=800,height=600)],reply_markup=method.reply_markup).as_(bot)
            self.messages[(msg.chat.id,msg.message_id)]=msg
            return msg
        if isinstance(method, (SendMessage, EditMessageText, SendPhoto, SendDocument)):
            mid=getattr(method,"message_id",None)
            if isinstance(method,EditMessageText):
                old=self.messages.get((int(method.chat_id),mid))
                if old and (old.photo or old.document):
                    raise TelegramBadRequest(method=method,message="Bad Request: there is no text in the message to edit")
            if mid is None:
                self.next_message_id+=1
                mid=self.next_message_id
            msg=Message(message_id=mid,date=datetime.now(UTC),chat=Chat(id=int(method.chat_id),type="private"),
                from_user=User(id=bot.id,is_bot=True,first_name="InfoBox"),
                text=getattr(method,"text",None),caption=getattr(method,"caption",None),reply_markup=getattr(method,"reply_markup",None) if hasattr(getattr(method,"reply_markup",None),"inline_keyboard") else None,
                photo=[PhotoSize(file_id="preview",file_unique_id="preview",width=800,height=600)] if isinstance(method,SendPhoto) else None,
                document=Document(file_id="document",file_unique_id="document",file_name="card.png") if isinstance(method,SendDocument) else None).as_(bot)
            self.messages[(msg.chat.id,msg.message_id)]=msg
            return msg
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
        with self.assertNoLogs("handlers", level="ERROR"):
            await self.dp.feed_update(self.bot, Update(update_id=self.updates, message=msg))

    async def callback(self, data, photo=False):
        self.updates += 1
        msg = Message(message_id=10, date=datetime.now(UTC), chat=Chat(id=self.uid, type="private"), from_user=User(id=self.bot.id, is_bot=True, first_name="InfoBox"), text=None if photo else "Экран", photo=[PhotoSize(file_id="preview",file_unique_id="preview",width=800,height=600)] if photo else None)
        q = CallbackQuery(id=str(self.updates), from_user=User(id=self.uid, is_bot=False, first_name="Тест"), chat_instance="test", message=msg, data=data)
        with self.assertNoLogs("handlers", level="ERROR"):
            await self.dp.feed_update(self.bot, Update(update_id=self.updates, callback_query=q))

    async def click_message(self, message, data):
        self.updates+=1
        current=self.session.messages[(message.chat.id,message.message_id)]
        q=CallbackQuery(id=str(self.updates),from_user=User(id=self.uid,is_bot=False,first_name="Тест"),chat_instance="test",message=current,data=data)
        with self.assertNoLogs("handlers", level="ERROR"):
            await self.dp.feed_update(self.bot,Update(update_id=self.updates,callback_query=q))

    async def test_preview_photo_buttons_survive_home_restart_and_save(self):
        await self.message("/start")
        await self.callback("hoi4:mode:new:tfr:event")
        await self.callback("build:superevent:editor")
        await self.message("Кефирстан")
        await self.callback("draft:back")
        photo=next(m for m in reversed(list(self.session.messages.values())) if m.photo)
        self.assertIsNone(photo.text)
        self.assertTrue(any(b.callback_data=="draft:save" for row in photo.reply_markup.inline_keyboard for b in row))
        # Actually click the bot's emitted photo, not a fabricated text message.
        for callback in ("draft:fields","hoi4:media:d","hoi4:options:d","draft:text","draft:export"):
            before=len(self.session.calls)
            await self.click_message(photo,callback)
            self.assertGreater(len(self.session.calls),before+1,callback)
            if callback in ("draft:fields", "hoi4:media:d", "hoi4:options:d"):
                calls = self.session.calls[before:]
                self.assertTrue(any(isinstance(c, SendMessage) for c in calls), callback)
                self.assertFalse(any(isinstance(c, EditMessageText) for c in calls), callback)
        await self.message("/start")
        await self.state.clear()
        await self.click_message(photo,"draft:fields")
        self.assertEqual((await self.state.get_data())["type"],"superevent")
        await self.click_message(photo,"draft:back")
        second=next(m for m in reversed(list(self.session.messages.values())) if m.photo)
        await self.click_message(second,"draft:save")
        page=(await self.db.get_user_pages(self.uid))[0]
        self.assertIsNone(await self.state.get_state())
        for preview in (photo,second):
            keyboard=self.session.messages[(preview.chat.id,preview.message_id)].reply_markup
            callbacks={b.callback_data for row in keyboard.inline_keyboard for b in row}
            self.assertNotIn("draft:save",callbacks)
            self.assertIn(f"p:e:{page.id}",callbacks)
            self.assertIn(f"hoi4:media:p{page.id}",callbacks)
        for callback in (f"p:e:{page.id}",f"hoi4:media:p{page.id}",f"hoi4:options:p{page.id}",f"p:txt:{page.id}",f"p:x:{page.id}",f"p:c:{page.id}"):
            before=len(self.session.calls)
            await self.click_message(photo,callback)
            self.assertGreater(len(self.session.calls),before+1,callback)
        self.assertEqual(len(await self.db.get_user_pages(self.uid)),2)

    async def test_document_preview_keyboard_is_upgraded_on_save(self):
        self.session.reject_photos=True
        await self.message("/start")
        await self.callback("hoi4:mode:new:tno:event")
        await self.callback("build:superevent:editor")
        await self.message("Карточка")
        await self.callback("draft:back")
        document=next(m for m in reversed(list(self.session.messages.values())) if m.document)
        await self.state.clear()
        before = len(self.session.calls)
        await self.click_message(document,"hoi4:options:d")
        calls = self.session.calls[before:]
        self.assertTrue(any(isinstance(c, SendMessage) for c in calls))
        self.assertFalse(any(isinstance(c, EditMessageText) for c in calls))
        self.assertEqual((await self.state.get_data())["type"],"superevent")
        for callback in ("hoi4:media:d", "hoi4:options:d", "draft:image", "draft:theme"):
            before = len(self.session.calls)
            await self.click_message(document, callback)
            calls = self.session.calls[before:]
            self.assertTrue(any(isinstance(c, SendMessage) for c in calls), callback)
            self.assertFalse(any(isinstance(c, EditMessageText) for c in calls), callback)
            expected = "Картинки HOI4" if callback in ("hoi4:media:d", "draft:image") else "Выбери стиль"
            self.assertTrue(any(isinstance(c, SendMessage) and expected in c.text for c in calls), callback)
        await self.click_message(document,"draft:save")
        page=(await self.db.get_user_pages(self.uid))[0]
        keyboard=self.session.messages[(document.chat.id,document.message_id)].reply_markup
        self.assertIn(f"p:e:{page.id}",{b.callback_data for row in keyboard.inline_keyboard for b in row})
        await self.click_message(document,f"p:x:{page.id}")
        self.assertIsNone(await self.state.get_state())

    async def test_hoi4_builtin_icon_picker_search_saved_cards_and_custom_upload(self):
        from hoi4_icons import matching
        for style in ("tno", "tfr"):
            with self.subTest(style=style):
                await self.message("/start")
                await self.callback(f"hoi4:mode:new:{style}:state")
                await self.callback("build:superevent:editor")
                await self.message("Тест")
                await self.callback("hoi4:media:d")
                await self.callback("hoi4:icons:d:ideology:0")
                sheet = next(m for m in reversed(list(self.session.messages.values())) if m.photo)
                self.assertIn("Значки идеологии", sheet.caption)
                await self.click_message(sheet, "hoi4:icons:d:ideology:9")
                self.assertIsInstance(self.session.calls[-1], EditMessageMedia)
                await self.click_message(sheet, "hoi4:iconsearch:d:ideology")
                query = "либерал" if style == "tno" else "liberal"
                await self.message(query)
                first = matching(style, "ideology", query)[0]
                sheet = next(m for m in reversed(list(self.session.messages.values())) if m.photo)
                self.assertIn(first["label"], sheet.caption)
                await self.click_message(sheet, f"hoi4:icon:d:ideology:{first['id']}")
                self.assertEqual((await self.state.get_data())["page_data"]["hoi4_icons"]["ideology"], first["id"])
                await self.callback("hoi4:icons:d:focus:0")
                focus = matching(style, "focus")[0]
                await self.callback(f"hoi4:icon:d:focus:{focus['id']}")
                await self.callback("hoi4:crop:d:focus")
                await self.callback("hoi4:adjust:d:focus:in", photo=True)
                await self.callback("draft:back")
                await self.callback("draft:save")
                page = (await self.db.get_user_pages(self.uid))[0]
                self.assertEqual(page.data["hoi4_icons"]["focus"], focus["id"])
                await self.callback(f"hoi4:media:p{page.id}")
                await self.callback(f"hoi4:icons:p{page.id}:ideology:0")
                other = matching("tfr" if style == "tno" else "tno", "ideology")[0]
                await self.callback(f"hoi4:icon:p{page.id}:ideology:{other['id']}")
                self.assertEqual((await self.db.get_page(page.id,self.uid)).data["hoi4_icons"]["ideology"], first["id"])
                await self.callback(f"hoi4:upload:p{page.id}:ideology")
                buf = BytesIO()
                Image.new("RGBA", (60, 60), "green").save(buf, "PNG")
                self.session.download = buf.getvalue()
                await self.message(document=Document(file_id="icon", file_unique_id="icon", file_name="icon.png", file_size=len(buf.getvalue())))
                page = await self.db.get_page(page.id, self.uid)
                self.assertNotIn("ideology", page.data["hoi4_icons"])
                self.assertIn("ideology", page.data["hoi4_media"])
                await self.callback(f"hoi4:icon:p{page.id}:ideology:{first['id']}")
                self.assertNotIn("ideology", (await self.db.get_page(page.id,self.uid)).data["hoi4_media"])
                await self.callback(f"hoi4:remove:p{page.id}:ideology")
                self.assertNotIn("ideology", (await self.db.get_page(page.id,self.uid)).data["hoi4_icons"])
                await self.callback(f"pd:{page.id}:yes")

    async def test_hoi4_party_editor_rejects_bad_input_without_losing_previous_value(self):
        from templates import get_template
        await self.message("/start")
        await self.callback("hoi4:mode:new:tno:state")
        await self.callback("build:superevent:editor")
        await self.message("Тест")
        tpl = get_template("superevent", {"hoi4_style":"tno", "hoi4_mode":"state"})
        index = next(i for i,f in enumerate(tpl.fields) if f.key == "parties")
        good = "ЛПК, 43, rgb(243, 190, 32)\nНПК, 57, red"
        await self.callback(f"df:{index}")
        await self.message(good)
        await self.callback(f"df:{index}")
        await self.message("ЛПК, -3, red")
        self.assertEqual((await self.state.get_data())["page_data"]["parties"], good)
        self.assertEqual(await self.state.get_state(), NewPage.edit_value.state)
        await self.message(good)
        await self.callback("draft:back")
        await self.callback("draft:save")
        page = (await self.db.get_user_pages(self.uid))[0]
        await self.callback(f"pe:{page.id}:s:{index}")
        await self.message("Новая, 100, blue")
        self.assertEqual((await self.db.get_page(page.id, self.uid)).data["parties"], "Новая, 100, blue")

    async def test_hoi4_selection_upload_resume_and_save(self):
        await self.message("/start")
        await self.callback("compose:superevent")
        await self.callback("hoi4:style:new:tno")
        await self.callback("hoi4:mode:new:tno:all")
        await self.callback("build:superevent:editor")
        await self.message("Кефирстан")
        d=await self.state.get_data()
        self.assertEqual(d["page_data"]["hoi4_mode"],"all")
        self.assertEqual(d["theme"],"tno")
        await self.callback("hoi4:media:d")
        for role,color in (("flag","yellow"),("portrait","blue"),("event","red")):
            await self.callback(f"hoi4:upload:d:{role}")
            buf=BytesIO()
            Image.new("RGB",(300,200),color).save(buf,"PNG")
            self.session.download=buf.getvalue()
            await self.message(document=Document(file_id="image",file_unique_id=role,file_name="image.png",mime_type="image/png",file_size=len(buf.getvalue())))
        d=await self.state.get_data()
        self.assertEqual(set(d["page_data"]["hoi4_media"]),{"flag","portrait","event"})
        self.assertEqual(len(d["page_data"]["images"]),3)
        await self.callback("menu:home")
        await self.state.clear()
        await self.callback("draft:resume")
        self.assertEqual((await self.state.get_data())["page_data"]["hoi4_style"],"tno")
        await self.callback("draft:back")
        self.assertTrue(any(isinstance(c,SendPhoto) for c in self.session.calls))
        await self.callback("draft:save")
        pages=await self.db.get_user_pages(self.uid)
        self.assertEqual(len(pages),1)
        page=pages[0]
        await self.callback(f"hoi4:options:p{page.id}")
        await self.callback(f"hoi4:mode:p{page.id}:tfr:state")
        page=await self.db.get_page(page.id,self.uid)
        self.assertEqual(page.theme,"fire_rises")
        self.assertEqual(page.data["hoi4_mode"],"state")
        self.assertIsNone(page.preview_path)
        self.assertEqual(len(page.data["hoi4_media"]),3)
        # Another user's card cannot be changed through forged callbacks.
        other=await self.db.save_page(Page(self.uid+1,"superevent","Чужая",data={"title":"Чужая"}))
        await self.callback(f"hoi4:mode:p{other.id}:tno:all")
        self.assertNotIn("hoi4_mode",(await self.db.get_page(other.id,self.uid+1)).data)

    async def test_hoi4_upload_back_commands_crop_and_saved_actions(self):
        await self.message("/start")
        await self.callback("hoi4:mode:new:tno:all")
        await self.callback("build:superevent:editor")
        await self.message("Кефирстан")
        await self.callback("hoi4:upload:d:flag")
        await self.message("/start")
        self.assertIsNone(await self.state.get_state())
        self.assertEqual((await self.db.get_draft(self.uid))["page_data"]["title"],"Кефирстан")
        await self.callback("draft:resume")
        await self.callback("hoi4:upload:d:flag")
        await self.callback("hoi4:media:d")
        self.assertEqual(await self.state.get_state(),NewPage.review.state)
        buf=BytesIO()
        Image.new("RGB",(500,100),"red").save(buf,"PNG")
        self.session.download=buf.getvalue()
        await self.callback("hoi4:upload:d:flag")
        await self.message(document=Document(file_id="image",file_unique_id="flag",file_name="flag.png",mime_type="image/png",file_size=len(buf.getvalue())))
        await self.callback("hoi4:crop:d:flag")
        await self.callback("hoi4:adjust:d:flag:cover",photo=True)
        await self.callback("hoi4:adjust:d:flag:in",photo=True)
        self.assertTrue(any(isinstance(c,EditMessageMedia) for c in self.session.calls))
        crop=(await self.state.get_data())["page_data"]["hoi4_crop"]["flag"]
        self.assertEqual(crop["fit"],"cover")
        self.assertEqual(crop["zoom"],110)
        await self.callback("draft:back")
        await self.callback("draft:export")
        self.assertTrue(any(isinstance(c,SendDocument) for c in self.session.calls))
        await self.callback("draft:save")
        page=(await self.db.get_user_pages(self.uid))[0]
        await self.callback(f"hoi4:upload:p{page.id}:portrait")
        await self.message(document=Document(file_id="image",file_unique_id="portrait",file_name="portrait.png",mime_type="image/png",file_size=len(buf.getvalue())))
        self.assertIsNone(await self.state.get_state())
        page=await self.db.get_page(page.id,self.uid)
        self.assertIn("portrait",page.data["hoi4_media"])
        self.assertEqual(page.data["hoi4_crop"]["flag"]["zoom"],110)
        await self.callback(f"hoi4:remove:p{page.id}:portrait")
        self.assertNotIn("portrait",(await self.db.get_page(page.id,self.uid)).data["hoi4_media"])
        await self.callback(f"p:e:{page.id}")
        from templates import get_template
        tpl=get_template("superevent",page.data)
        index=next(i for i,f in enumerate(tpl.fields) if f.key=="leader")
        await self.callback(f"pe:{page.id}:s:{index}")
        await self.message("Тимофей Рализм")
        self.assertEqual((await self.db.get_page(page.id,self.uid)).data["leader"],"Тимофей Рализм")
        await self.callback(f"p:txt:{page.id}")
        await self.callback(f"p:x:{page.id}")
        await self.callback(f"p:c:{page.id}")
        pages=await self.db.get_user_pages(self.uid)
        self.assertEqual(len(pages),2)
        copied=next(p for p in pages if p.id!=page.id)
        self.assertEqual(copied.data["hoi4_crop"]["flag"]["zoom"],110)
        await self.callback(f"pd:{copied.id}:yes")
        self.assertIsNone(await self.db.get_page(copied.id,self.uid))
        # Even the historical single-image buttons must use the role picker.
        await self.callback(f"pa:{page.id}:image")
        self.assertIsNone(await self.state.get_state())
        self.assertTrue(any((getattr(c,"text",None) or "").startswith("<b>Картинки HOI4") for c in self.session.calls))
        await self.callback(f"hoi4:upload:p{page.id}:flag")
        await self.message("/cancel")
        self.assertIsNone(await self.state.get_state())

    async def test_hoi4_all_wizards_reach_preview(self):
        from templates import get_template
        await self.message("/start")
        for style,mode in (("tno","state"),("tno","event"),("tno","news"),("tno","all"),("tfr","state"),("tfr","event"),("tfr","all")):
            with self.subTest(style=style,mode=mode):
                await self.callback(f"hoi4:mode:new:{style}:{mode}")
                await self.callback("build:superevent:wizard")
                await self.message("Кефирстан")
                d=await self.state.get_data()
                tpl=get_template("superevent",d["page_data"])
                for key in tpl.wizard[1:]:
                    await self.callback("wiz:skip")
                self.assertEqual(await self.state.get_state(),NewPage.review.state)
                self.assertEqual((await self.state.get_data())["i"], len(tpl.wizard))
                await self.callback("draft:back")
                self.assertEqual(await self.state.get_state(),NewPage.review.state)
                self.assertTrue((await self.state.get_data())["preview_path"])
                await self.callback("draft:save")
                self.assertIsNone(await self.db.get_draft(self.uid))

    async def test_news_limit_preserves_previous_value_in_all_input_modes(self):
        from templates import get_template
        await self.message("/start")
        await self.callback("hoi4:mode:new:tno:news")
        await self.callback("build:superevent:editor")
        await self.message("Кефирстан")
        tpl=get_template("superevent",(await self.state.get_data())["page_data"])
        i=next(i for i,f in enumerate(tpl.fields) if f.key=="news_body")
        await self.callback(f"df:{i}")
        self.assertIn("0/400",self.session.calls[-1].text)
        await self.message("А"*401)
        self.assertEqual(await self.state.get_state(),NewPage.edit_value.state)
        self.assertNotIn("news_body",(await self.state.get_data())["page_data"])
        self.assertIn("401/400",self.session.calls[-1].text)
        await self.message("Кефирстан "*40)
        self.assertEqual(len((await self.state.get_data())["page_data"]["news_body"]),399)
        await self.callback("draft:save")
        page=(await self.db.get_user_pages(self.uid))[0]
        await self.callback(f"pe:{page.id}:s:{i}")
        self.assertIn("399/400",self.session.calls[-1].text)
        await self.message("А"*401)
        self.assertEqual(len((await self.db.get_page(page.id,self.uid)).data["news_body"]),399)
        self.assertEqual(await self.state.get_state(),"EditPage:value")
        await self.message("Текст\n"*60)
        self.assertIn("не помещаются",self.session.calls[-1].text)
        await self.message("Исправлено")
        self.assertEqual((await self.db.get_page(page.id,self.uid)).data["news_body"],"Исправлено")
        await self.callback("menu:home")
        await self.callback("hoi4:mode:new:tno:news")
        await self.callback("build:superevent:paste")
        await self.message("Название: Газета\nТекст газеты: "+"А"*1400)
        self.assertEqual(await self.state.get_state(),Navigation.paste.state)
        self.assertIn("1400/400",self.session.calls[-1].text)
        await self.message("Название: Газета\nТекст газеты: Короткий текст")
        self.assertEqual((await self.state.get_data())["page_data"]["news_body"],"Короткий текст")
        # Wizard rejects the same overflow before advancing its field index.
        await self.callback("menu:home")
        await self.callback("draft:discard:yes")
        await self.callback("hoi4:mode:new:tno:news")
        await self.callback("build:superevent:wizard")
        await self.message("Газета")
        await self.callback("wiz:skip")  # headline
        before=(await self.state.get_data())["i"]
        await self.message("А"*401)
        self.assertEqual((await self.state.get_data())["i"],before)
        self.assertIn("401/400",self.session.calls[-1].text)

    async def test_hoi4_paste_keeps_style_and_mode(self):
        await self.message("/start")
        await self.callback("hoi4:mode:new:tno:news")
        await self.callback("build:superevent:paste")
        await self.message("Название: Кефирстан\nЗаголовок газеты: Союз автономий\nТекст газеты: Проверка")
        d=await self.state.get_data()
        self.assertEqual(d["type"],"superevent")
        self.assertEqual(d["theme"],"tno")
        self.assertEqual(d["page_data"]["hoi4_mode"],"news")
        self.assertEqual(d["page_data"]["news_body"],"Проверка")

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
