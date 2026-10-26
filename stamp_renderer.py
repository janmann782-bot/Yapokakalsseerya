"""Vector-like circular seals rendered locally, with a transparent PNG export."""
from __future__ import annotations

import math
import os
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFont, ImageOps

from media import page_images

STAMP_LAYOUT_VERSION = 1
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


def face(size):
    return ImageFont.truetype(str(ROOT / "DejaVuSans-Bold.ttf"), size)


def arc_font(text):
    for size in range(58, 19, -1):
        font = face(size)
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
        if key == "stamp_color":
            ink_color(text)
        if key in ("stamp_top", "stamp_bottom"):
            arc_font(" ".join(text.upper().split()))
        if key == "stamp_center":
            center_text(Image.new("RGBA", (1, 1)), text, (290, 600, 734, 730), ink_color(None))
    except ValueError as exc:
        return str(exc)
    return None


def arc_text(canvas, text, bottom, color):
    text = " ".join(str(text or "").upper().split())
    if not text:
        return
    font = arc_font(text)
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


def center_text(canvas, text, box, color):
    from hoi4_renderer import wrap

    if not str(text or "").strip():
        return
    text = str(text).strip().upper()
    x0, y0, x1, y1 = box
    for size in range(66, 19, -1):
        font = face(size)
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
    for key in (*LIMITS, "stamp_color"):
        error = stamp_field_error("stamp", key, data.get(key))
        if error:
            raise ValueError(error)
    color = ink_color(data.get("stamp_color"))
    canvas = Image.new("RGBA", (1024, 1024))
    draw = ImageDraw.Draw(canvas)
    for radius, width in ((460, 7), (445, 2), (335, 5)):
        draw.ellipse((512-radius, 512-radius, 512+radius, 512+radius), outline=color, width=width)
    for x in (122, 902):
        points = [(x + (15 if i % 2 == 0 else 6) * math.cos(-math.pi/2 + i*math.pi/5),
                   512 + (15 if i % 2 == 0 else 6) * math.sin(-math.pi/2 + i*math.pi/5)) for i in range(10)]
        draw.polygon(points, fill=color)
    arc_text(canvas, data.get("stamp_top"), False, color)
    arc_text(canvas, data.get("stamp_bottom"), True, color)
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
                logo = ImageOps.contain(logo.crop(bounds), (270, 270), Image.Resampling.LANCZOS)
                canvas.alpha_composite(logo, ((1024-logo.width)//2, 300 + (270-logo.height)//2))
                has_logo = True
    box = (290, 600, 734, 730) if has_logo else (280, 350, 744, 690)
    center_text(canvas, data.get("stamp_center"), box, color)
    return canvas


def render_stamp(page, root, output, quality="high"):
    result = stamp_image(page.data or {}, root)
    size = {"standard": 768, "high": 1024, "ultra": 2048}.get(quality, 1024)
    if size != 1024:
        result = result.resize((size, size), Image.Resampling.LANCZOS)
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
