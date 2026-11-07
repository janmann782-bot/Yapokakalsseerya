"""Produce faithful before/after HOI4 cards using the bundled PSD renderers."""
from __future__ import annotations

import base64
import importlib.util
import io
from pathlib import Path
import zipfile

from PIL import Image, ImageDraw, ImageFont, ImageOps

import hoi4_renderer as after
from hoi4_icons import icon_image, matching


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "previews" / "kefirstan"
OUT.mkdir(parents=True, exist_ok=True)
MEDIA = OUT / "media"
MEDIA.mkdir(exist_ok=True)

# Saved from the user's existing Kefirstan flag and Ralizm portrait in their Library.
with zipfile.ZipFile(io.BytesIO(base64.b64decode((ROOT / "preview_kefirstan_assets.b64").read_text().strip()))) as bundle:
    for name in ("portrait.jpg", "flag.jpg"):
        (MEDIA / name).write_bytes(bundle.read(name))

spec = importlib.util.spec_from_file_location("hoi4_renderer_before", ROOT / "preview_renderer_before.py")
before = importlib.util.module_from_spec(spec)
spec.loader.exec_module(before)


def padded_icon(image, name):
    icon = image.convert("RGBA")
    icon.thumbnail((112, 112), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    canvas.alpha_composite(icon, ((160 - icon.width) // 2, (160 - icon.height) // 2))
    canvas.save(MEDIA / name)
    return name


def alliance_emblem():
    flag = Image.open(MEDIA / "flag.jpg").convert("RGBA")
    # Use the existing globe-and-eagle insignia from the flag as an alliance emblem.
    crop = flag.crop((0, 18, 79, 107))
    circle = ImageOps.fit(crop, (114, 114), Image.Resampling.LANCZOS)
    mask = Image.new("L", circle.size)
    ImageDraw.Draw(mask).ellipse((1, 1, 112, 112), fill=255)
    circle.putalpha(mask)
    return circle


def demo_data(style):
    ideology_catalog = matching(style, "ideology")
    focus_catalog = matching(style, "focus")
    if not ideology_catalog or not focus_catalog:
        raise RuntimeError("Required bundled style icons are missing")
    files = {
        "ideology": padded_icon(icon_image(ideology_catalog[0]["id"]), f"{style}_ideology.png"),
        "focus": padded_icon(icon_image(focus_catalog[0]["id"]), f"{style}_focus.png"),
        "alliance": padded_icon(alliance_emblem(), f"{style}_alliance.png"),
        "flag": "flag.jpg",
        "portrait": "portrait.jpg",
    }
    return {
        "title": "Кефирстан",
        "country_name": "Кефирстан",
        "alliance": "Кефирский союз",
        "leader": "Тимофей Рализм",
        "ruling_party": "Либертарианская партия Кефирстана (ЛПК)",
        "ideology": "Корпоративный минархизм",
        "elections": "Выборы 2061",
        "focus": "Свобода работает!",
        "hoi4_media": files,
        "hoi4_style": style,
    }


def compare(label, original, updated, destination):
    w = max(original.width, updated.width)
    s = 2 if w < 800 else 1
    original = original.resize((original.width * s, original.height * s), Image.Resampling.NEAREST) if s > 1 else original
    updated = updated.resize((updated.width * s, updated.height * s), Image.Resampling.NEAREST) if s > 1 else updated
    header = 68
    gap = 16
    width = original.width + updated.width + gap
    height = max(original.height, updated.height) + header
    out = Image.new("RGB", (width, height), "#16191f")
    out.paste(original.convert("RGB"), (0, header))
    out.paste(updated.convert("RGB"), (original.width + gap, header))
    face = ImageFont.truetype(str(ROOT / "DejaVuSans-Bold.ttf"), 28)
    draw = ImageDraw.Draw(out)
    draw.text((24, 17), f"{label}   ДО (1.12.0)", font=face, fill="#f5f5f5")
    draw.text((original.width + gap + 24, 17), f"{label}   ПОСЛЕ (1.12.2)", font=face, fill="#a9f38f")
    out.save(destination, optimize=True)
    return out


results = []
for style in ("tno", "tfr"):
    data = demo_data(style)
    old_card = before.state_card(data, MEDIA, style)
    new_card = after.state_card(data, MEDIA, style)
    old_card.save(OUT / f"{style.upper()}_before.png")
    new_card.save(OUT / f"{style.upper()}_after.png")
    result = compare(style.upper(), old_card, new_card, OUT / f"{style.upper()}_before_after.png")
    results.append(result)
    print(style, "native bot renderer:", old_card.size, new_card.size)

gap = 32
stack = Image.new("RGB", (max(im.width for im in results), sum(im.height for im in results) + gap), "#101219")
y = 0
for im in results:
    stack.paste(im, ((stack.width - im.width) // 2, y))
    y += im.height + gap
stack.save(OUT / "Kefirstan_Ralizm_TNO_TFR_before_after.png", optimize=True)
print("Rendered", OUT)
