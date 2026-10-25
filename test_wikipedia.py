from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from demo_kefirstan import DATA
from models import Page
from pillow_renderer import render_pillow
from renderer import make_html
from templates import COUNTRY
from themes import get_theme
from ui import fields_kb
from wiki_layout import country_groups


class WikipediaTests(unittest.TestCase):
    def test_country_keeps_every_populated_template_field(self):
        data = {f.key: f.key for f in COUNTRY.fields}
        visible = {f.key for _, fields in country_groups(COUNTRY, data) for f in fields}
        separately_rendered = {"card_type_label", "title", "official_name", "description", "image_caption", "anthem", "anthem_duration", "alt_name", "motto"}
        self.assertEqual((visible | separately_rendered) & set(data), set(data))

    def test_all_field_pages_remain_accessible(self):
        data = {"custom_fields": [{"name": str(i), "value": i} for i in range(180)]}
        seen = set()
        offset = 0
        while True:
            kb = fields_kb(COUNTRY, data, page_id=7, offset=offset)
            buttons = [b for row in kb.inline_keyboard for b in row]
            self.assertLessEqual(len(buttons), 100)
            seen.update(b.callback_data for b in buttons if b.callback_data.startswith("pe:"))
            next_button = next((b for b in buttons if b.text == "Следующие поля"), None)
            if next_button is None:
                break
            offset = int(next_button.callback_data.rsplit(":", 1)[1])
        self.assertEqual(len(seen), len(COUNTRY.fields) + 180)

    def test_fallback_renders_country_and_cyrillic(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            page = Page(1, "country", "Кефирстан", data=dict(DATA))
            output = render_pillow(page, tmp, quality="high", output=Path(tmp) / "preview_country.png", watermark=False)
            with Image.open(output) as im:
                self.assertGreater(im.height, im.width)
                self.assertEqual(im.getpixel((0, 0)), (255, 255, 255))


class WikipediaBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_templates_fit_and_show_full_text(self):
        from playwright.async_api import async_playwright
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Two differently proportioned symbols exercise the country grid.
            Image.new("RGB", (600, 400), "#ffe000").save(root / "media_flag.png")
            Image.new("RGB", (200, 600), "#224488").save(root / "media_coat.png")
            cases = [
                Page(1, "country", "Кефирстан", data={**DATA, "images": ["media_flag.png", "media_coat.png"], "population": "Население пока не указано", "area": "Территория пока не указана"}),
                Page(1, "region", "Очень длинное название автономной республики", data={"title": "Очень длинное название автономной республики", "administrative_center": "Каменный Мост", "country": "Кефирстан"}),
                Page(1, "person", "Тимофей Рализм", data={"title": "Тимофей Рализм", "occupation": "Президент", "description": "Длинная строка без пробелов: " + "А" * 200}),
                Page(1, "battle", "Проверка длинной карточки битвы", data={"date": "28 июня 2057 года", "side_1": "Кефирстан", "side_2": "Йогуртстан", "commander_1": "Имя командира", "strength_2": "123 456"}),
            ]
            async with async_playwright() as pw:
                try:
                    browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
                except Exception as exc:
                    self.skipTest(f"Chromium unavailable: {exc}")
                try:
                    tab = await browser.new_page(viewport={"width": 880, "height": 900})
                    for page in cases:
                        with self.subTest(type=page.type):
                            await tab.set_content(make_html(page, work_dir=root, watermark=False))
                            await tab.evaluate("document.fonts.ready")
                            overflow = await tab.locator("#infobox").evaluate("el => [el, ...el.querySelectorAll('*')].filter(x => x.clientWidth > 0 && x.scrollWidth > x.clientWidth + 1).map(x => x.className)")
                            self.assertEqual(overflow, [])
                            self.assertEqual(await tab.locator("#infobox").evaluate("el => getComputedStyle(el).backgroundColor"), "rgb(255, 255, 255)")
                            self.assertIn(page.data.get("title", page.title), await tab.locator("h1").inner_text())
                            self.assertTrue(await tab.evaluate("document.fonts.check(\"13px 'Wikipedia Sans'\", 'Кефирстан')"))
                            if page.type == "country":
                                boxes = await tab.locator(".gallery:not(.map) figure").evaluate_all("els => els.map(e => ({x:e.offsetLeft, y:e.offsetTop}))")
                                self.assertEqual(boxes[0]["y"], boxes[1]["y"])
                                self.assertNotEqual(boxes[0]["x"], boxes[1]["x"])
                finally:
                    await browser.close()


if __name__ == "__main__":
    unittest.main()
