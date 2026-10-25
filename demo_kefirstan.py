"""Render a real country card through the bot's database and PNG pipeline.

Usage: python demo_kefirstan.py --output-dir /absolute/path
No Telegram token or running bot is required. The database is demonstration-only.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from pathlib import Path

from db import Db
from models import Page
from renderer import render_page

ROOT = Path(__file__).resolve().parent

# Author's current registry, 2062. No guessed population, GDP or territory.
# https://chatgpt.com/library?file_id=libfile_905406a8b9f08191aae46497d18bb6a6&account_id=personal
DATA = {
    "title": "Кефирстан",
    "official_name": "Союз Автономных Республик Кефирстан",
    "capital": "Каменный Мост",
    "government": "Президентская республика",
    "head_of_state": "Тимофей Рализм",
    "head_of_government": "Павел Каменец",
    "parliament": "Союзное собрание\nСовет автономий",
    "legislature_seats": "240 депутатов\n32 делегата",
    "ruling_party": "Либертарианская Партия Кефирстана",
    "ideology": "Корпоративный минархизм",
    "constitution": "Конституция 1961 года\nКонституционный акт 15 августа 2050 года",
    "currency": "Мол",
    "sections": [{"title": "Автономные республики", "fields": [
        {"name": "Состав союза", "value": "Кефирия\nТвороград\nМолозорь"},
    ]}],
    "description": "Союз автономных республик. Союзная власть ведет внешнюю политику, оборону, денежное обращение и общие правовые вопросы. Автономии сохраняют широкую самостоятельность в местном управлении.",
    "images": ["media_kefirstan_flag.png"],
    "image_captions": {"media_kefirstan_flag.png": "Флаг Кефирстана"},
}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "demo_output")
    args = parser.parse_args()
    dest = args.output_dir.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "media_flag.png", dest / "media_kefirstan_flag.png")
    db = Db(dest / "demo.db")
    await db.init()
    page = await db.save_page(Page(owner_id=1, type="country", title="Кефирстан", theme="light", data=json.loads(json.dumps(DATA))))
    saved = await db.get_page(page.id, page.owner_id)
    assert saved is not None
    output = await render_page(saved, dest, output="Kefirstan.png", watermark=False)
    (dest / "Kefirstan.json").write_text(json.dumps(DATA, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    asyncio.run(main())
