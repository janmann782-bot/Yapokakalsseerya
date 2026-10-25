"""Build a UI contact sheet from real dispatcher responses, using local Telegram."""
from __future__ import annotations

import argparse
import asyncio
import html
from pathlib import Path

from aiogram.methods import SendMessage, EditMessageText
from playwright.async_api import async_playwright

from renderer import font_css
from test_navigation import NavigationTests
from version import __version__


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("demo_output"))
    dest = parser.parse_args().output_dir.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    scenario = NavigationTests("test_editor_draft_survives_home_and_fsm_restart")
    await scenario.asyncSetUp()
    screens = []

    def capture(label):
        response = next(c for c in reversed(scenario.session.calls) if isinstance(c, (SendMessage, EditMessageText)) and c.reply_markup is not None)
        buttons = []
        for row in response.reply_markup.inline_keyboard:
            buttons.append('<div class="buttons">' + ''.join('<div class="button">' + html.escape(b.text) + '</div>' for b in row) + '</div>')
        screens.append('<section><h2>' + label + '</h2><div class="phone"><div class="bar">InfoBox Bot</div><div class="chat"><div class="message">' + response.text.replace('\n', '<br>') + '</div>' + ''.join(buttons) + '</div></div></section>')

    try:
        await scenario.message("/start")
        capture("Меню")
        await scenario.callback("compose:country")
        capture("Создание")
        await scenario.callback("build:country:editor")
        await scenario.message("Кефирстан")
        capture("Редактор")
    finally:
        await scenario.asyncTearDown()

    markup = '''<!doctype html><html lang="ru"><meta charset="utf-8"><style>'''+font_css()+'''
* { box-sizing: border-box; }
body { margin:0; background:#fff; color:#000; font:15px/1.4 'Wikipedia Sans',Arial,sans-serif; padding:36px; }
h1 {font-size:28px;margin:0 0 8px;} .note {margin:0 0 26px;color:#54595d;font-size:13px;}
main {display:grid;grid-template-columns:repeat(3,360px);gap:24px;align-items:start;}
h2 {font-size:17px;font-weight:400;margin:0 0 12px;}
.phone {border:1px solid #a2a9b1;background:#f5f5f5;min-height:840px;}
.bar {padding:18px 16px;background:#fff;border-bottom:1px solid #c8ccd1;font-size:17px;font-weight:700;}
.chat {padding:14px 10px;} .message {padding:15px 13px;background:#fff;border:1px solid #d5d8dc;margin-bottom:6px;overflow-wrap:anywhere;}
.buttons {display:flex;gap:5px;margin-top:5px;} .button {flex:1;text-align:center;padding:11px 6px;background:#fff;border:1px solid #b9bec4;font-size:13px;line-height:1.35;}
blockquote {margin:12px 0 0;border-left:2px solid #72777d;padding-left:10px;}
</style><h1>InfoBox Bot - '''+__version__+'''</h1><p class="note">Схема экранов. Тексты и кнопки взяты из ответов обработчиков бота. Цвета Telegram зависят от темы приложения</p><main>'''+''.join(screens)+'''</main></html>'''
    (dest / "Interface.html").write_text(markup, encoding="utf-8")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            page = await browser.new_page(viewport={"width": 1200, "height": 1100}, device_scale_factor=1.5)
            await page.set_content(markup)
            await page.evaluate("document.fonts.ready")
            output = dest / f"Infobox_UI_{__version__}.png"
            await page.screenshot(path=str(output), full_page=True)
            print(output)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
