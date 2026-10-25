from pathlib import Path
import tempfile
import unittest

from PIL import Image
from models import Page
from renderer import render_page
from hoi4_renderer import (
    Hoi4TextOverflow,
    text_box,
    wrap,
    font,
    image_roles,
    party_data,
)
from templates import get_template
from parser import parse_text


class Hoi4Tests(unittest.IsolatedAsyncioTestCase):
    async def test_every_format_renders_with_exact_canvas(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGB", (800, 400), "#edbd25").save(root / "media_test.png")
            for style in ("tno", "tfr"):
                for mode in ("state", "event", "all", "news"):
                    if mode == "news" and style == "tfr":
                        continue
                    with self.subTest(style=style, mode=mode):
                        data = {
                            "title": "Кефирстан",
                            "hoi4_mode": mode,
                            "hoi4_style": style,
                            "leader": "Тимофей Рализм",
                            "parties": "ЛПК | 30 | #ffcc00\nДругая | 20 | #123456",
                            "body": "Тест переноса русского текста",
                            "hoi4_media": {
                                "flag": "media_test.png",
                                "event": "media_test.png",
                                "portrait": "media_test.png",
                                "news": "media_test.png",
                            },
                        }
                        page = Page(
                            1,
                            "superevent",
                            "Кефирстан",
                            theme="tno" if style == "tno" else "fire_rises",
                            data=data,
                        )
                        output = await render_page(
                            page,
                            root,
                            output=f"preview_{style}_{mode}.png",
                            watermark=False,
                        )
                        with Image.open(output) as im:
                            im.load()
                            expected = {
                                "tno": {
                                    "state": (863, 391),
                                    "event": (1049, 904),
                                    "all": (1920, 1080),
                                    "news": (618, 683),
                                },
                                "tfr": {
                                    "state": (940, 504),
                                    "event": (1050, 748),
                                    "all": (2006, 1128),
                                },
                            }
                            self.assertEqual(im.size, expected[style][mode])
                        self.assertEqual(page.data["_hoi4_layout"], 1)

    async def test_old_superevent_still_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Page(
                1,
                "superevent",
                "Старый заголовок",
                theme="fire_rises",
                data={"body": "Старая цитата", "button_text": "Продолжить"},
            )
            self.assertTrue(
                (await render_page(page, tmp, output="preview_old.png")).is_file()
            )
            self.assertEqual(
                get_template("superevent", page.data).wizard,
                ("title", "body", "button_text"),
            )

    def test_overflow_is_explicit_and_long_words_wrap(self):
        canvas = Image.new("RGBA", (200, 100))
        face = font("tno", 18)
        self.assertTrue(
            all(face.getlength(x) <= 100 for x in wrap("А" * 100, face, 100))
        )
        with self.assertRaisesRegex(Hoi4TextOverflow, "Сократи текст"):
            text_box(canvas, "Текст " * 1000, (0, 0, 100, 50), "tno", 24, "Цитата")
        with self.assertRaises(ValueError):
            party_data("ЛПК | nan | #ffcc00")

    def test_old_image_fallback_does_not_undo_removal(self):
        self.assertEqual(image_roles({"images": ["old.png"]}), {"event": "old.png"})
        self.assertEqual(image_roles({"images": ["old.png"], "hoi4_media": {}}), {})

    def test_editor_fields_follow_format(self):
        for mode in ("state", "event", "news", "all"):
            tpl = get_template("superevent", {"hoi4_style": "tno", "hoi4_mode": mode})
            keys = {x.key for x in tpl.fields}
            self.assertEqual("leader" in keys, mode in ("state", "all"))
            self.assertEqual("body" in keys, mode in ("event", "all"))
            self.assertEqual("news_body" in keys, mode in ("news", "all"))
            self.assertTrue(set(tpl.wizard) <= keys)
        self.assertNotIn(
            "news_body",
            {
                x.key
                for x in get_template(
                    "superevent", {"hoi4_style": "tfr", "hoi4_mode": "all"}
                ).fields
            },
        )

    def test_paste_hoi4_recognizes_new_fields(self):
        parsed = parse_text(
            "Тип: HOI4 Карточка (бета)\nНазвание: Кефирстан\nЛидер: Тимофей Рализм\nИдеология: Корпоративный минархизм\nЗаголовок события: Проверка"
        )
        self.assertEqual(parsed.type, "superevent")
        self.assertEqual(parsed.data["leader"], "Тимофей Рализм")
        self.assertEqual(parsed.data["event_title"], "Проверка")
