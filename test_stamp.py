from pathlib import Path
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
import tempfile
import unittest

from PIL import Image, ImageDraw

from models import Page
from renderer import render_page
from parser import parse_text
from field_validation import data_error, field_error
from stamp_renderer import ink_color, stamp_image
from themes import theme_allowed
from ui import send_png


class StampTests(unittest.IsolatedAsyncioTestCase):
    def test_russian_text_input_and_colors(self):
        parsed = parse_text("Тип: печать\nНазвание печати: Фонд\nТекст сверху: Кефирстан\nТекст снизу: Каменный Мост\nТекст в центре: ФНВ\nЦвет печати: синий")
        self.assertEqual(parsed.type, "stamp")
        self.assertEqual(parsed.data["stamp_top"], "Кефирстан")
        self.assertEqual(parsed.data["stamp_center"], "ФНВ")
        self.assertIsNone(data_error(parsed.type, parsed.data))
        self.assertEqual(parse_text("Название: Фонд\nТекст сверху: Кефирстан").type, "stamp")
        self.assertEqual(ink_color("черный"), (17,17,17,255))
        self.assertEqual(ink_color("#ff0000"), (255,0,0,255))
        self.assertIsNotNone(field_error("stamp", "stamp_color", "неизвестный"))
        self.assertIsNotNone(field_error("stamp", "stamp_color", "rgb(999,0,0)"))
        self.assertIsNotNone(field_error("stamp", "stamp_top", "Ш"*61))
        self.assertIsNotNone(field_error("stamp", "stamp_center", "Ш"*100))
        oversized = parse_text("Тип: печать\nНазвание: Фонд\nТекст сверху: " + "Ш"*1500)
        self.assertEqual(len(oversized.data["stamp_top"]),1500)
        self.assertIn("1500/60",data_error("stamp",oversized.data))
        self.assertTrue(theme_allowed("stamp", "stamp"))
        self.assertFalse(theme_allowed("tno", "stamp"))

    async def test_export_has_transparent_background_at_all_sizes(self):
        data = {"stamp_top":"СОЮЗ АВТОНОМНЫХ РЕСПУБЛИК КЕФИРСТАН", "stamp_bottom":"КАМЕННЫЙ МОСТ", "stamp_center":"ФОНД\nНАЦИОНАЛЬНОГО\nВЫБОРА", "stamp_color":"синий"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for quality, size in (("standard",768),("high",1024),("ultra",2048)):
                path = await render_page(Page(1,"stamp","Фонд",theme="stamp",data=dict(data)), root, quality, output=f"{quality}.png")
                with Image.open(path) as im:
                    self.assertEqual(im.mode, "RGBA")
                    self.assertEqual(im.size,(size,size))
                    self.assertEqual(im.getpixel((0,0))[3],0)
                    self.assertEqual(im.getpixel((size//2,size//4))[3],0)
                    bounds = im.getchannel("A").getbbox()
                    self.assertGreater(bounds[0],20)
                    self.assertLess(bounds[2],size-20)
                    self.assertGreater(im.getchannel("A").histogram()[255],1000)

    def test_rectangular_worn_stamp(self):
        from stamp_renderer import stamp_field_error
        data = {"stamp_shape": "прямоугольная", "stamp_texture": "потертый",
                "stamp_top": "СОЮЗ АВТОНОМНЫХ РЕСПУБЛИК КЕФИРСТАН",
                "stamp_bottom": "КАМЕННЫЙ МОСТ", "stamp_center": "ФОНД\nНАЦИОНАЛЬНОГО\nВЫБОРА"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worn = stamp_image(data, root)
            self.assertEqual(worn.size, (1024, 640))
            self.assertEqual(worn.getpixel((0, 0))[3], 0)
            self.assertEqual(worn.tobytes(), stamp_image(data, root).tobytes())
            clean = stamp_image(dict(data, stamp_texture="четкий"), root)
            wa, ca = worn.getchannel("A"), clean.getchannel("A")
            self.assertLess(sum(wa.getdata()), sum(ca.getdata()))
            self.assertGreater(sum(wa.getdata()), sum(ca.getdata()) * .8)
            self.assertTrue(all(w <= c for w, c in zip(wa.getdata(), ca.getdata())))
            self.assertEqual(wa.getbbox(), ca.getbbox())
            self.assertIsNotNone(stamp_field_error("stamp", "stamp_shape", "треугольник"))
            self.assertIsNotNone(data_error("stamp", dict(data, stamp_texture="мусор")))
            parsed = parse_text("Тип: печать\nФорма печати: прямоугольная\nОттиск: потертый")
            self.assertEqual(parsed.data["stamp_texture"], "потертый")

    def test_wear_levels_are_validated_stable_and_progressive(self):
        from stamp_renderer import wear_level
        self.assertEqual(wear_level({}), 0)
        self.assertEqual(wear_level({"stamp_texture": "потертый"}), 35)
        self.assertEqual(wear_level({"stamp_wear": "0", "stamp_texture": "потертый"}), 0)
        self.assertEqual(wear_level({"stamp_wear": "75%"}), 75)
        for value in ("-1", "101", "50.5", "много", "nan"):
            self.assertIsNotNone(field_error("stamp", "stamp_wear", value))
            self.assertIsNotNone(data_error("stamp", {"stamp_wear": value}))
        parsed = parse_text("Тип: печать\nУровень потертости: 50")
        self.assertEqual(parsed.data["stamp_wear"], "50")
        with tempfile.TemporaryDirectory() as tmp:
            for shape in ("круглая", "прямоугольная"):
                previous = None
                for level in (0, 25, 50, 75, 100):
                    data = {"stamp_shape": shape, "stamp_center": "ФНВ", "stamp_wear": str(level)}
                    im = stamp_image(data, Path(tmp))
                    alpha = im.getchannel("A").tobytes()
                    self.assertEqual(im.tobytes(), stamp_image(data, Path(tmp)).tobytes())
                    if previous is not None:
                        self.assertLess(sum(alpha), sum(previous))
                        self.assertTrue(all(a <= b for a, b in zip(alpha, previous)))
                    previous = alpha

    def test_custom_symbol_is_tinted_and_white_paper_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            symbol = Image.new("RGB",(200,200),"white")
            ImageDraw.Draw(symbol).rectangle((50,50,150,150),fill="black")
            symbol.save(root/"media_symbol.png")
            im = stamp_image({"images":["media_symbol.png"],"stamp_color":"красный"}, root)
            self.assertEqual(im.getpixel((512,435)),ink_color("красный"))
            self.assertEqual(im.getpixel((512,250))[3],0)
            self.assertEqual(im.getpixel((512,650))[3],0)
            outside = stamp_image({"images":["../private.png"]}, root)
            self.assertEqual(outside.getpixel((512,435))[3],0)

    async def test_photo_preview_is_white_but_document_keeps_original_alpha(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"print.png"
            original = stamp_image({"stamp_top":"Кефирстан"}, Path(tmp))
            original.save(path)
            msg = SimpleNamespace(answer_photo=AsyncMock(), answer_document=AsyncMock())
            await send_png(msg,path,"Печать")
            preview = msg.answer_photo.await_args.args[0]
            with Image.open(BytesIO(preview.data)) as image:
                self.assertEqual(image.mode,"RGB")
                self.assertEqual(image.getpixel((0,0)),(255,255,255))
            await send_png(msg,path,"Печать",document=True)
            self.assertEqual(Path(msg.answer_document.await_args.args[0].path),path)
            with Image.open(path) as image:
                self.assertEqual(image.getpixel((0,0))[3],0)
