"""Procedural seals rendered locally, with a transparent PNG export."""
from __future__ import annotations

import math
import os
import random
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFont, ImageOps, ImageFilter

from media import page_images

STAMP_LAYOUT_VERSION = 4
ROOT = Path(__file__).resolve().parent
LIMITS = {"stamp_top": 60, "stamp_bottom": 60, "stamp_center": 100}
COLORS = {"синий": "#164a9b", "синяя": "#164a9b", "черный": "#111111",
          "черная": "#111111", "красный": "#b02630", "красная": "#b02630",
          "зеленый": "#21683f", "зеленая": "#21683f", "фиолетовый": "#66358a",
          "фиолетовая": "#66358a"}


def ink_color(value):
    value = str(value or "синий").strip().casefold().replace("ё", "е")
    try:
        rgb = ImageColor.getrgb(COLORS.get(value, value))
        if any(channel < 0 or channel > 255 for channel in rgb):
            raise ValueError
    except ValueError:
        raise ValueError("Укажи цвет: синий, черный, красный, зеленый, фиолетовый или HEX, например #164a9b") from None
    return (*rgb[:3], 255)



def stamp_option(key, value):
    text = str(value or "").strip().casefold().replace("ё", "е")
    choices = {
        "stamp_shape": {"": "circle", "круглая": "circle", "круг": "circle", "circle": "circle",
                        "прямоугольная": "rectangle", "прямоугольный": "rectangle", "прямоугольник": "rectangle", "rectangle": "rectangle"},
        "stamp_texture": {"": "clean", "четкий": "clean", "четкая": "clean", "clean": "clean",
                          "потертый": "worn", "потертая": "worn", "worn": "worn"},
    }
    if text not in choices[key]:
        raise ValueError("Укажи форму: круглая или прямоугольная" if key == "stamp_shape" else
                         "Укажи оттиск: четкий или потертый")
    return choices[key][text]


def wear_level(data):
    value = data.get("stamp_wear")
    if value is None or str(value).strip() == "":
        return 35 if stamp_option("stamp_texture", data.get("stamp_texture")) == "worn" else 0
    text = str(value).strip().removesuffix("%").strip()
    if not text.isascii() or not text.isdecimal() or not 0 <= int(text) <= 100:
        raise ValueError("Укажи потертость от 0 до 100. 0 - четкий оттиск, 100 - сильная потертость")
    return int(text)


def worn_ink(canvas, level=35, seed="180"):
    seed = str(seed)
    # Separate stable random streams make increasing wear remove more ink only.
    rng = random.Random(seed + ":grain")
    wear = Image.new("L", canvas.size, 255)
    draw = ImageDraw.Draw(wear)
    for _ in range(round(14857 * level / 100)):
        x, y = rng.randrange(canvas.width), rng.randrange(canvas.height)
        radius = rng.choice((1, 1, 2, 3))
        draw.ellipse((x, y, x+radius, y+radius), fill=0)
    rng = random.Random(seed + ":scratches")
    for _ in range(round(129 * level / 100)):
        x, y = rng.randrange(canvas.width), rng.randrange(canvas.height)
        draw.line((x, y, x+rng.randrange(8, 35), y+rng.randrange(-3, 4)), fill=0, width=1)
    # Broad faded patches mixed with sharp grain and directional scratches.
    rng = random.Random(seed + ":patches")
    patches = Image.new("L", canvas.size, 255)
    patch_draw = ImageDraw.Draw(patches)
    for _ in range(round(55 * level / 100)):
        x, y = rng.randrange(canvas.width), rng.randrange(canvas.height)
        w, h = rng.randrange(12, 75), rng.randrange(5, 25)
        patch_draw.ellipse((x, y, x+w, y+h), fill=70)
    patches = patches.filter(ImageFilter.GaussianBlur(4))
    wear = ImageChops.darker(wear, patches)
    canvas.putalpha(ImageChops.multiply(canvas.getchannel("A"), wear))
    return canvas


def stamp_font_path(data, root):
    from fonts_catalog import resolve_font_files, resolve_user_font, list_bundled_families
    key = str(data.get("stamp_font") or data.get("_font_key") or "default")
    if key == "default":
        return ROOT / "DejaVuSans-Bold.ttf"
    if key.startswith("user:"):
        uid = data.get("_font_user_id")
        path = resolve_user_font(root, int(uid), key) if uid is not None else None
    elif key in {k for k, _ in list_bundled_families()}:
        regular, bold = resolve_font_files(key)
        path = bold or regular
    else:
        path = None
    if path is None:
        raise ValueError("Шрифт недоступен. Выбери другой или загрузи его заново")
    return path


def face(size, font_path=None):
    return ImageFont.truetype(str(font_path or ROOT / "DejaVuSans-Bold.ttf"), size)


def arc_font(text, font_path=None):
    for size in range(58, 19, -1):
        font = face(size, font_path)
        if sum(font.getlength(char) + 2 for char in text) <= math.radians(140) * 390:
            return font
    raise ValueError("Надпись по кругу слишком длинная. Сократи текст")


def stamp_field_error(page_type, key, value):
    if page_type != "stamp" or not value:
        return None
    text = str(value).strip()
    if key in LIMITS and len(text) > LIMITS[key]:
        return f"Символов: {len(text)}/{LIMITS[key]}. Сократи надпись"
    try:
        if key == "stamp_wear":
            wear_level({"stamp_wear": value})
        if key in ("stamp_shape", "stamp_texture"):
            stamp_option(key, text)
        if key == "stamp_color":
            ink_color(text)
        if key in ("stamp_top", "stamp_bottom"):
            arc_font(" ".join(text.upper().split()))
        if key == "stamp_center":
            center_text(Image.new("RGBA", (1, 1)), text, (290, 600, 734, 730), ink_color(None))
    except ValueError as exc:
        return str(exc)
    return None


def arc_text(canvas, text, bottom, color, font_path=None):
    text = " ".join(str(text or "").upper().split())
    if not text:
        return
    font = arc_font(text, font_path)
    advances = [font.getlength(char) + 2 for char in text]
    offset = -sum(advances) / 2
    ascent, descent = font.getmetrics()
    for char, advance in zip(text, advances):
        angle = (90 - math.degrees((offset + advance/2) / 390) if bottom else
                 -90 + math.degrees((offset + advance/2) / 390))
        if not char.isspace():
            glyph = Image.new("RGBA", (math.ceil(advance) + 20, ascent + descent + 20))
            ImageDraw.Draw(glyph).text((10, 10 + ascent), char, font=font, fill=color, anchor="ls")
            rotation = 90 - angle if bottom else -90 - angle
            glyph = glyph.rotate(rotation, Image.Resampling.BICUBIC, expand=True)
            radians = math.radians(angle)
            center = (512 + 390 * math.cos(radians), 512 + 390 * math.sin(radians))
            canvas.alpha_composite(glyph, (round(center[0] - glyph.width/2), round(center[1] - glyph.height/2)))
        offset += advance


def center_text(canvas, text, box, color, font_path=None):
    from hoi4_renderer import wrap

    if not str(text or "").strip():
        return
    text = str(text).strip().upper()
    x0, y0, x1, y1 = box
    for size in range(66, 19, -1):
        font = face(size, font_path)
        if any(font.getlength(word) > x1-x0 for word in text.split()):
            continue
        lines = wrap(text, font, x1-x0)
        step = sum(font.getmetrics()) + 6
        if len(lines) * step <= y1-y0:
            break
    else:
        raise ValueError("Центральная надпись слишком длинная. Сократи текст")
    draw = ImageDraw.Draw(canvas)
    y = y0 + (y1-y0 - len(lines)*step)//2
    for line in lines:
        draw.text(((x0+x1-font.getlength(line))/2, y), line, font=font, fill=color, anchor="lt")
        y += step


def stamp_image(data, root):
    for key in (*LIMITS, "stamp_color", "stamp_shape", "stamp_texture", "stamp_wear"):
        error = stamp_field_error("stamp", key, data.get(key))
        if error:
            raise ValueError(error)
    color = ink_color(data.get("stamp_color"))
    font_path = stamp_font_path(data, root)
    rectangular = stamp_option("stamp_shape", data.get("stamp_shape")) == "rectangle"
    canvas = Image.new("RGBA", (1024, 640) if rectangular else (1024, 1024))
    draw = ImageDraw.Draw(canvas)
    if rectangular:
        draw.rectangle((35, 35, 989, 605), outline=color, width=7)
        draw.rectangle((49, 49, 975, 591), outline=color, width=2)
        draw.line((65, 200, 959, 200), fill=color, width=3)
        draw.line((65, 495, 959, 495), fill=color, width=3)
        center_text(canvas, data.get("stamp_top"), (75, 65, 949, 185), color, font_path)
        center_text(canvas, data.get("stamp_bottom"), (75, 510, 949, 575), color, font_path)
    else:
        for radius, width in ((460, 7), (445, 2), (335, 5)):
            draw.ellipse((512-radius, 512-radius, 512+radius, 512+radius), outline=color, width=width)
        for x in (122, 902):
            points = [(x + (15 if i % 2 == 0 else 6) * math.cos(-math.pi/2 + i*math.pi/5),
                       512 + (15 if i % 2 == 0 else 6) * math.sin(-math.pi/2 + i*math.pi/5)) for i in range(10)]
            draw.polygon(points, fill=color)
        arc_text(canvas, data.get("stamp_top"), False, color, font_path)
        arc_text(canvas, data.get("stamp_bottom"), True, color, font_path)
    images = page_images(data)
    has_logo = False
    if images:
        path = (Path(root) / str(images[0])).resolve()
        if path.parent == Path(root).resolve() and path.is_file():
            with Image.open(path) as source:
                logo = ImageOps.exif_transpose(source).convert("RGBA")
            # Ink-only emblem: white paper becomes transparent, original alpha is kept.
            alpha = ImageChops.multiply(ImageOps.invert(ImageOps.grayscale(logo)), logo.getchannel("A"))
            bounds = alpha.getbbox()
            if bounds:
                logo = Image.new("RGBA", logo.size, color)
                logo.putalpha(alpha)
                logo_size = 150 if rectangular else 270
                logo = ImageOps.contain(logo.crop(bounds), (logo_size, logo_size), Image.Resampling.LANCZOS)
                logo_top = 215 if rectangular else 300
                canvas.alpha_composite(logo, ((1024-logo.width)//2, logo_top + (logo_size-logo.height)//2))
                has_logo = True
    box = (290, 600, 734, 730) if has_logo else (280, 350, 744, 690)
    if rectangular:
        box = (85, 375, 939, 485) if has_logo else (85, 215, 939, 480)
    center_text(canvas, data.get("stamp_center"), box, color, font_path)
    level = wear_level(data)
    return worn_ink(canvas, level, data.get("stamp_seed", "180")) if level else canvas


def render_stamp(page, root, output, quality="high"):
    page.data.setdefault("stamp_seed", uuid4().hex)
    result = stamp_image(page.data, root)
    size = {"standard": 768, "high": 1024, "ultra": 2048}.get(quality, 1024)
    if size != 1024:
        result = result.resize((size, round(size * result.height / result.width)), Image.Resampling.LANCZOS)
    destination = Path(output)
    temporary = destination.with_name(destination.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("wb") as stream:
            result.save(stream, "PNG")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
