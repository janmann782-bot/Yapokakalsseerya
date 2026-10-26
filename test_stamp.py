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
            self.assertLess(sum(wa.tobytes()), sum(ca.tobytes()))
            self.assertGreater(sum(wa.tobytes()), sum(ca.tobytes()) * .8)
            self.assertTrue(all(w <= c for w, c in zip(wa.tobytes(), ca.tobytes())))
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

    async def test_procedural_seed_persists_and_fonts_render(self):
        import asyncio
        import shutil
        from fonts_catalog import user_fonts_dir, resolve_user_font
        from stamp_renderer import ROOT
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = user_fonts_dir(root, 17)
            shutil.copy(ROOT / "LiberationSerif-Regular.ttf", folder / "MyFont.ttf")
            data = {"stamp_top": "КЕФИРСТАН", "stamp_center": "ФНВ", "stamp_wear": "75"}
            page = Page(17, "stamp", "ФНВ", theme="stamp", data=dict(data))
            first = await render_page(page, root, "high", user_id=17, output="first.png")
            seed = page.data["stamp_seed"]
            again = await render_page(page, root, "high", user_id=17, output="again.png")
            self.assertEqual(first.read_bytes(), again.read_bytes())
            self.assertEqual(page.data["stamp_seed"], seed)
            other = Page(17, "stamp", "ФНВ", theme="stamp", data=dict(data))
            second = await render_page(other, root, "high", user_id=17, output="second.png")
            self.assertNotEqual(seed, other.data["stamp_seed"])
            self.assertNotEqual(first.read_bytes(), second.read_bytes())
            data.update(stamp_wear="0", stamp_seed="fixed", _font_user_id=17)
            plain = stamp_image(data, root).tobytes()
            custom = stamp_image(dict(data, stamp_font="user:MyFont.ttf"), root).tobytes()
            self.assertNotEqual(plain, custom)
            self.assertEqual(stamp_image(dict(data, _font_key="user:MyFont.ttf"), root).tobytes(), custom)
            # No shared mutable active font: concurrent rendering stays isolated.
            images = await asyncio.gather(
                asyncio.to_thread(stamp_image, data, root),
                asyncio.to_thread(stamp_image, dict(data, stamp_font="user:MyFont.ttf"), root))
            self.assertEqual(images[0].tobytes(), plain)
            self.assertEqual(images[1].tobytes(), custom)
            self.assertIsNone(resolve_user_font(root, 17, "user:../MyFont.ttf"))
            self.assertIsNone(resolve_user_font(root, 18, "user:MyFont.ttf"))
            with self.assertRaises(ValueError):
                stamp_image(dict(data, stamp_font="user:missing.ttf"), root)

    def test_oval_rings_separators_tilt_and_logo_only(self):
        from PIL import ImageChops
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            oval=stamp_image({"stamp_shape":"овальная"},root)
            self.assertEqual(oval.size,(1024,740))
            one=stamp_image({"stamp_rings":"1","stamp_separator":"нет"},root)
            two=stamp_image({"stamp_rings":"2","stamp_separator":"нет"},root)
            self.assertEqual(one.getpixel((512,177))[3],0)
            self.assertGreater(two.getpixel((512,177))[3],0)
            dots=stamp_image({"stamp_separator":"точки"},root)
            none=stamp_image({"stamp_separator":"нет"},root)
            self.assertGreater(dots.getpixel((122,512))[3],0)
            self.assertEqual(none.getpixel((122,512))[3],0)
            tilted=stamp_image({"stamp_shape":"овальная","stamp_angle":"8"},root)
            self.assertGreater(tilted.height,oval.height)
            self.assertEqual(tilted.getpixel((0,0))[3],0)
            symbol=Image.new("RGBA",(100,100));ImageDraw.Draw(symbol).ellipse((5,5,95,95),fill="black")
            symbol.save(root/"media_logo.png")
            for shape in ("круглая","овальная","прямоугольная"):
                data={"stamp_shape":shape,"images":["media_logo.png"],"stamp_logo_mode":"вместо текста"}
                only=stamp_image(data,root)
                with_text=stamp_image(dict(data,stamp_center="ЭТОТ ТЕКСТ СКРЫТ"),root)
                self.assertEqual(only.tobytes(),with_text.tobytes())
            for key,value in (("stamp_rings","7"),("stamp_width","0"),("stamp_angle","31"),("stamp_separator","треугольник")):
                self.assertIsNotNone(field_error("stamp",key,value))

    def test_document_placement_is_lossless_outside_stamp(self):
        from stamp_document import read_document, place_stamp
        source=Image.new("RGBA",(1000,1400),(240,238,230,255))
        buf=BytesIO();source.save(buf,"PNG")
        document=read_document(buf.getvalue())
        self.assertEqual(document.tobytes(),source.tobytes())
        stamp=Image.new("RGBA",(200,100),(0,0,255,255))
        for position in range(9):
            result=place_stamp(document,stamp,position,25)
            self.assertEqual(result.size,source.size)
            self.assertEqual(document.tobytes(),source.tobytes())
            self.assertEqual(result.getpixel((0,0)),source.getpixel((0,0)))
            from PIL import ImageChops
            bounds=ImageChops.difference(result.convert("RGB"),source.convert("RGB")).getbbox()
            self.assertEqual(bounds[2]-bounds[0],250)
            self.assertEqual(bounds[3]-bounds[1],125)
            col,row=position%3,position//3
            self.assertEqual(bounds[0],round(30+(1000-60-250)*col/2))
            self.assertEqual(bounds[1],round(30+(1400-60-125)*row/2))
        with self.assertRaises(ValueError):
            read_document(b"not an image")
        with self.assertRaises(ValueError):
            place_stamp(document,stamp,9,25)

    def test_centered_visible_ink_and_weight(self):
        from stamp_renderer import center_text, ROOT
        for filename in ("DejaVuSans-Bold.ttf","LiberationSerif-Regular.ttf"):
            for text in ("СЕКРЕТНО", "КОПИЯ\nВЕРНА", "ФОНД\nНАЦИОНАЛЬНОГО\nВЫБОРА"):
                for strength in (0,3):
                    image=Image.new("RGBA",(1024,640))
                    center_text(image,text,(85,80,939,560),(0,0,255,255),ROOT/filename,120,strength)
                    x0,y0,x1,y1=image.getchannel("A").getbbox()
                    self.assertLessEqual(abs((x0+x1)/2-512),1)
                    self.assertLessEqual(abs((y0+y1)/2-320),1)
        with tempfile.TemporaryDirectory() as tmp:
            data={"stamp_shape":"прямоугольная","stamp_center":"СЕКРЕТНО","stamp_rings":"0"}
            im=stamp_image(data,Path(tmp))
            x0,y0,x1,y1=im.getchannel("A").getbbox()
            self.assertLessEqual(abs((x0+x1)/2-512),1)
            self.assertLessEqual(abs((y0+y1)/2-320),1)
            normal=stamp_image(dict(data,stamp_weight="400"),Path(tmp))
            heavy=stamp_image(dict(data,stamp_weight="900"),Path(tmp))
            self.assertGreater(sum(heavy.getchannel("A").tobytes()),sum(normal.getchannel("A").tobytes()))

    def test_six_frames_and_border_styles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for shape in ("круглая","овальная","прямоугольная"):
                base={"stamp_shape":shape,"stamp_separator":"нет","stamp_width":"5"}
                self.assertIsNone(stamp_image(dict(base,stamp_rings="0"),root).getbbox())
                for count in range(1,7):
                    image=stamp_image(dict(base,stamp_rings=str(count)),root)
                    alpha=image.getchannel("A")
                    # Six distinct bands on the vertical centerline, with gaps.
                    stop=512 if shape=="круглая" else 370 if shape=="овальная" else 130
                    values=[bool(alpha.getpixel((512,y))) for y in range(30,stop)]
                    bands=sum(v and (i==0 or not values[i-1]) for i,v in enumerate(values))
                    self.assertEqual(bands,count,(shape,count))
                solid=stamp_image(dict(base,stamp_rings="3"),root)
                for style in ("пунктир","точки"):
                    patterned=stamp_image(dict(base,stamp_rings="3",stamp_border_style=style),root)
                    self.assertLess(sum(patterned.getchannel("A").tobytes()),sum(solid.getchannel("A").tobytes()))
                # Thick nested frames keep the content area usable.
                stamp_image(dict(base,stamp_rings="6",stamp_width="24",stamp_center="ФНВ"),root)
            for key,value in (("stamp_weight","399"),("stamp_weight","901"),("stamp_rings","7"),("stamp_width","25")):
                self.assertIsNotNone(data_error("stamp",{key:value}))

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
