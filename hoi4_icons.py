"""Read the original PSD icon catalog without Photoshop or psd-tools at runtime."""

from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path
import zipfile

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parent / "assets" / "hoi4" / "icons"
PAGE_SIZE = 9


@lru_cache(maxsize=1)
def catalog():
    return {entry["id"]: entry for entry in json.loads((ROOT / "catalog.json").read_text())}


def entry_for(data, role):
    entry = catalog().get((data.get("hoi4_icons") or {}).get(role))
    if entry and entry["role"] == role and entry["style"] == data.get("hoi4_style", "tno"):
        return entry
    return None


@lru_cache(maxsize=64)
def _image(key):
    if key not in catalog():
        raise ValueError("Такого значка нет в шаблоне")
    with zipfile.ZipFile(ROOT / "icons.zip") as archive:
        with Image.open(BytesIO(archive.read(key + ".png"))) as source:
            return source.convert("RGBA")


def icon_image(key):
    return _image(key).copy()


def matching(style, role, query=""):
    def norm(text):
        return text.casefold().replace("ё", "е").replace("_", " ")
    terms = norm(query).split()
    return [entry for entry in catalog().values()
            if entry["style"] == style and entry["role"] == role
            and all(term in norm(entry["label"] + " " + entry["category"] + " " + entry["source_layer"]) for term in terms)]


def icon_sheet(entries):
    from hoi4_renderer import font, wrap
    canvas = Image.new("RGB", (768, 200 * max(1, (len(entries) + 2) // 3)), "black")
    draw = ImageDraw.Draw(canvas)
    for i, entry in enumerate(entries):
        x, y = (i % 3) * 256, (i // 3) * 200
        image = ImageOps.contain(icon_image(entry["id"]), (116, 116))
        canvas.paste(image, (x + (256 - image.width) // 2, y + 9), image)
        label = str(i + 1) + ". " + entry["label"].replace("_", " ")
        for size in range(16, 11, -1):
            face = font("tno", size)
            lines = wrap(label, face, 234)
            if len(lines) <= 3:
                break
        for j, line in enumerate(lines):
            draw.text((x + 11, y + 130 + j * 19), line, font=face, fill="#dbe4e5")
    stream = BytesIO()
    canvas.save(stream, "PNG")
    return stream.getvalue()
