from pathlib import Path
import tempfile
import unittest

from PIL import Image
from models import Page
from renderer import render_page
from hoi4_renderer import (
    Hoi4TextOverflow,
    LAYOUT_VERSION,
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
                        self.assertEqual(page.data["_hoi4_layout"], LAYOUT_VERSION)

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

    def test_psd_foreground_stays_above_photo(self):
        from PIL import ImageChops, ImageDraw
        from hoi4_renderer import asset, event_card, state_card, news_card

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGB", (1600, 100), "#ff0000").save(root / "media_red.png")
            for style in ("tno", "tfr"):
                data = {
                    "title": "",
                    "hoi4_style": style,
                    "hoi4_media": {
                        "event": "media_red.png",
                        "flag": "media_red.png",
                        "portrait": "media_red.png",
                    },
                }
                rendered = event_card(data, root, style)
                factor = 1 if style == "tno" else 2
                front = asset(style + "_event_front", factor)
                opaque = front.getchannel("A").point(lambda a: 255 if a == 255 else 0)
                if style == "tno":
                    # The adaptive native button is intentionally composed later.
                    ImageDraw.Draw(opaque).rectangle((0, 820, 1048, 879), fill=0)
                self.assertGreater(sum(opaque.histogram()[1:]), 1000)
                diff = ImageChops.difference(
                    rendered.convert("RGB"), front.convert("RGB")
                )
                only_opaque = Image.composite(diff, Image.new("RGB", diff.size), opaque)
                self.assertIsNone(
                    only_opaque.getbbox(), style + " frame changed under photo"
                )
                state = state_card(data, root, style)
                plate = asset(style + "_state_front", factor)
                point = (11, 245) if style == "tfr" else (13, 378)
                x, y = point[0] * factor, point[1] * factor
                expected = Image.alpha_composite(
                    Image.new("RGBA", plate.size, "black"), plate
                )
                self.assertEqual(
                    state.getpixel((x, y))[:3], expected.getpixel((x, y))[:3]
                )
            news = news_card({"hoi4_media": {"news": "media_red.png"}}, root)
            front = asset("tno_news_front")
            for point in ((205, 624), (214, 642)):
                self.assertEqual(news.getpixel(point)[:3], front.getpixel(point)[:3])

    def test_flag_aspect_and_crop_controls(self):
        from hoi4_renderer import picture

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGB", (500, 100), "red").save(root / "media_wide.png")
            canvas = Image.new("RGBA", (200, 200), "black")
            picture(canvas, root, "media_wide.png", (0, 0, 200, 200), contain=True)
            red = canvas.getchannel("R").point(lambda a: 255 if a > 200 else 0)
            self.assertEqual(red.getbbox(), (0, 80, 200, 120))
            src = Image.new("RGB", (400, 100), "red")
            from PIL import ImageDraw

            ImageDraw.Draw(src).rectangle((200, 0, 399, 99), fill="blue")
            src.save(root / "media_halves.png")
            for pan, expected in ((0, (255, 0, 0)), (100, (0, 0, 255))):
                canvas = Image.new("RGBA", (100, 100), "black")
                picture(
                    canvas,
                    root,
                    "media_halves.png",
                    (0, 0, 100, 100),
                    settings={"fit": "cover", "x": pan, "y": 50, "zoom": 100},
                )
                self.assertEqual(canvas.getpixel((50, 50))[:3], expected)

    def test_icons_use_their_own_cells_and_party_pie_is_visible(self):
        from hoi4_renderer import state_card

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, color in [
                ("alliance", "red"),
                ("focus", "blue"),
                ("ideology", "lime"),
            ]:
                Image.new("RGB", (100, 100), color).save(root / f"media_{name}.png")
            for style in ("tno", "tfr"):
                data = {
                    "hoi4_media": {
                        name: f"media_{name}.png"
                        for name in ("alliance", "focus", "ideology")
                    },
                    "parties": "А | 1 | #ffff00",
                }
                rendered = state_card(data, root, style)
                coords = {
                    "tno": [(790, 60), (293, 322), (278, 60), (294, 191)],
                    "tfr": [(872, 66), (328, 424), (328, 66), (332, 280)],
                }[style]
                for point, color in zip(
                    coords[:3], [(255, 0, 0), (0, 0, 255), (0, 255, 0)]
                ):
                    self.assertEqual(rendered.getpixel(point)[:3], color)
                yellow = rendered.getpixel(coords[3])
                self.assertGreater(yellow[0], 180)
                self.assertGreater(yellow[1], 180)
                self.assertLess(yellow[2], 100)

    def test_newspaper_limit_and_layout_are_checked_before_render(self):
        from hoi4_limits import news_field_error
        from hoi4_renderer import news_card, crop_settings

        self.assertIsNone(news_field_error("superevent", "news_body", "Ш" * 400))
        self.assertIn("401/400", news_field_error("superevent", "news_body", "А" * 401))
        self.assertIn(
            "переносы", news_field_error("superevent", "news_body", "Текст\n" * 60)
        )
        self.assertEqual(crop_settings({}, "portrait")["fit"], "contain")
        self.assertEqual(
            crop_settings(
                {"hoi4_crop": {"portrait": {"fit": "cover", "zoom": 120}}}, "portrait"
            )["zoom"],
            120,
        )
        parsed = parse_text("Тип: HOI4\nНазвание: Газета\nТекст газеты: " + "А" * 1400)
        self.assertEqual(len(parsed.data["news_body"]), 1400)
        with tempfile.TemporaryDirectory() as tmp:
            image = news_card({"news_body": "Ш" * 400}, tmp)
            self.assertEqual(image.size, (618, 683))
            with self.assertRaisesRegex(Hoi4TextOverflow, "401/400"):
                news_card({"news_body": "А" * 401}, tmp)

    def test_tfr_keeps_native_flag_glass_and_event_type_scale(self):
        from hoi4_renderer import asset, state_card, event_card
        from PIL import ImageChops

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGB", (600, 400), "red").save(root / "media_flag.png")
            front = asset("tfr_state_front", 2)
            point = (128, 68)
            alpha = front.getpixel(point)[3]
            self.assertGreater(alpha, 0, "Native flag glass was erased")
            self.assertLess(alpha, 255, "Flag glass must remain transparent")
            rendered = state_card(
                {"hoi4_media": {"flag": "media_flag.png"}}, root, "tfr"
            )
            expected = Image.alpha_composite(
                Image.new("RGBA", front.size, "red"), front
            )
            self.assertEqual(rendered.getpixel(point), expected.getpixel(point))
            empty = event_card({}, root, "tfr").convert("RGB")
            title = event_card({"event_title": "TEST"}, root, "tfr").convert("RGB")
            bounds = ImageChops.difference(title, empty).getbbox()
            self.assertIsNotNone(bounds)
            self.assertLessEqual(bounds[3] - bounds[1], 22)
            quote = event_card({"body": "TEST"}, root, "tfr").convert("RGB")
            bounds = ImageChops.difference(quote, empty).getbbox()
            self.assertLess(
                bounds[1], 520, "Quote must start at the top of the native panel"
            )
            button = event_card({"button_text": "TEST"}, root, "tfr").convert("RGB")
            bounds = ImageChops.difference(button, empty).getbbox()
            self.assertLessEqual(bounds[3] - bounds[1], 20)
