"""Render Kefirstan through the real bot pipeline.

python demo_hoi4.py --output-dir /absolute/path --source /path/to/existing_Ralizm_image.png
The optional source is the author's existing image, not a generated portrait.
"""

import argparse
import asyncio
import shutil
from pathlib import Path

from PIL import Image
from db import Db
from models import Page
from renderer import render_page

ROOT = Path(__file__).resolve().parent
# Current author's registry: libfile_905406a8b9f08191aae46497d18bb6a6, 2062.
DATA = {
    "title": "Кефирстан - 2062",
    "hoi4_mode": "all",
    "country_name": "САР Кефирстан",
    "leader": "Тимофей Рализм",
    "ruling_party": "Либертарианская партия Кефирстана",
    "ideology": "Корпоративный минархизм",
    "event_title": "Власть по контракту",
    "body": "Канцелярия влияет на назначения. Парламентский контроль упирается в закрытые договоры. Автономии защищают свои доходы",
    "button_text": "Кефирстан, 2062",
    "newspaper_name": "Государственный реестр",  # Demonstration masthead, not a canon publication.
    "news_title": "Союз трех автономий",
    "news_body": "Кефирия, Твороград и Молозорь сохраняют широкую самостоятельность.\\n\\nСоюзная власть ведет внешнюю политику, оборону и денежное обращение.\\n\\nПрезидент - Тимофей Рализм. Глава правительства - Павел Каменец.\\n\\nСоюзное собрание - 240 депутатов. Совет автономий - 32 делегата.\\n\\nСтолица - Каменный Мост. Валюта - мол.".replace(
        "\\n", "\n"
    ),
    "news_date": "2062 год",
    "news_button": "Государственное устройство",
    "hoi4_media": {"flag": "media_flag.png"},
    "images": ["media_flag.png"],
}


async def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output-dir", type=Path, required=True)
    cli.add_argument("--source", type=Path)
    args = cli.parse_args()
    root = args.output_dir.resolve()
    root.mkdir(exist_ok=True, parents=True)
    shutil.copyfile(ROOT / "media_flag.png", root / "media_flag.png")
    data = {**DATA, "hoi4_media": dict(DATA["hoi4_media"])}
    if args.source:
        with Image.open(args.source) as im:
            w, h = im.size
            im.crop(
                (int(w * 0.50), int(h * 0.175), int(w * 0.75), int(h * 0.355))
            ).save(root / "media_portrait.png")
            im.crop((int(w * 0.23), int(h * 0.13), int(w * 0.96), int(h * 0.46))).save(
                root / "media_event.png"
            )
        data["hoi4_media"].update(
            portrait="media_portrait.png",
            event="media_event.png",
            news="media_event.png",
        )
        data["images"] = list(data["hoi4_media"].values())
    db = Db(root / "demo.db")
    await db.init()
    for style in ("tno", "tfr"):
        page = await db.save_page(
            Page(
                1,
                "superevent",
                data["title"],
                theme="tno" if style == "tno" else "fire_rises",
                data={**data, "hoi4_style": style},
            )
        )
        print(
            await render_page(
                page,
                root,
                output=f"Kefirstan_HOI4_{style.upper()}.png",
                watermark=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
