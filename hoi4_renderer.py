"""HOI4 cards assembled from the author's PSD artwork. No Photoshop at runtime."""

from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageChops

from media import page_images
from templates import hoi4_mode

ASSETS = Path(__file__).resolve().parent / "assets" / "hoi4"
LAYOUT_VERSION = 10
INK = "#dbe4e5"

# Font sizes in rendered pixels. Larger fields get more room; text_box
# still reduces the size for long content instead of drawing over the PSD.
STATE_TEXT_SIZES = {
    "tno": {
        "title": 28, "alliance": 26, "leader": 28,
        "party": 31, "ideology": 31, "elections": 30, "focus": 34,
    },
    "tfr": {
        "title": 27, "alliance": 26, "leader": 27,
        "party": 29, "ideology": 29, "elections": 29, "focus": 34,
    },
}
EVENT_QUOTE_SIZE = {"tno": 34, "tfr": 22}
EVENT_BUTTON_SIZE = {"tno": 29, "tfr": 23}


class Hoi4TextOverflow(ValueError):
    pass


def style_for(page):
    return "tno" if page.theme == "tno" else "tfr"


def image_roles(data):
    roles = dict(data.get("hoi4_media") or {})
    # Existing superevents had a single untagged image.
    images = page_images(data)
    if images and "hoi4_media" not in data:
        roles["event"] = images[0]
    return roles


def media_roles(data):
    mode = hoi4_mode(data)
    roles = {}
    if mode in ("state", "all"):
        roles.update(
            flag="Флаг",
            portrait="Портрет лидера",
            ideology="Значок идеологии",
            alliance="Значок альянса",
            focus="Значок фокуса",
        )
    if mode in ("event", "all"):
        roles["event"] = "Картинка суперевента"
    if mode == "news" or (mode == "all" and data.get("hoi4_style") == "tno"):
        roles["news"] = "Фото газеты"
    return roles


def font(style, size, role="body"):
    if role == "news":
        name = ASSETS / "OldTyper.ttf"
    elif style == "tno":
        name = ASSETS / ("Aldrich.ttf" if role == "title" else "Bombardier.ttf")
    else:
        name = Path(__file__).resolve().parent / "PixeloidSans.otf"
    return ImageFont.truetype(str(name), size)


def wrap(text, face, width):
    lines = []
    for para in str(text).replace("\r", "\n").split("\n"):
        if not para:
            lines.append("")
            continue
        current = ""
        for word in para.split():
            if current and face.getlength(current + " " + word) > width:
                lines.append(current)
                current = ""
            # Split even a single long token; never let it escape its box.
            for char in (" " if current else "") + word:
                if current and face.getlength(current + char) > width:
                    lines.append(current)
                    current = ""
                current += char
        lines.append(current)
    return lines or [""]


def text_box(
    canvas,
    text,
    box,
    style,
    size,
    label,
    *,
    minimum=12,
    fill=INK,
    align="left",
    role="body",
    valign="center",
    line_height=None,
):
    text = str(text or "").strip()
    if not text:
        return
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    for px in range(size, minimum - 1, -1):
        face = font(style, px, role)
        lines = wrap(text, face, width)
        ascent, descent = face.getmetrics()
        step = (
            round(line_height * px / size)
            if line_height
            else ascent + descent + max(2, px // 6)
        )
        if len(lines) * step <= height:
            break
    else:
        raise Hoi4TextOverflow(
            f'Поле "{label}" не помещается. Сократи текст или выбери другой формат'
        )
    draw = ImageDraw.Draw(canvas)
    y = y0 if valign == "top" else y0 + (height - len(lines) * step) // 2
    for line in lines:
        w = face.getlength(line)
        x = (
            x0 + (width - w) / 2
            if align == "center"
            else x1 - w if align == "right" else x0
        )
        draw.text((x, y), line, font=face, fill=fill, anchor="lt", stroke_width=0)
        y += step


def asset(name, scale=1):
    with Image.open(ASSETS / (name + ".png")) as source:
        result = source.copy()
    if scale != 1:
        result = result.resize(
            (result.width * scale, result.height * scale), Image.Resampling.LANCZOS
        )
    return result


def scaled(box, scale):
    return tuple(round(x * scale) for x in box)


def crop_settings(data, role):
    saved = (data.get("hoi4_crop") or {}).get(role) or {}
    fit = saved.get(
        "fit",
        (
            "contain"
            if role in ("flag", "portrait", "ideology", "alliance", "focus")
            else "cover"
        ),
    )
    return dict(
        fit=fit if fit in ("contain", "cover") else "cover",
        x=max(0, min(100, int(saved.get("x", 50)))),
        y=max(0, min(100, int(saved.get("y", 50)))),
        zoom=max(100, min(300, int(saved.get("zoom", 100)))),
    )


def picture(
    canvas, root, path, box, *, grayscale=False, contain=False, settings=None, mask=None, source_image=None
):
    if source_image is None:
        if not path:
            return False
        base = Path(root).resolve()
        src = (base / str(path)).resolve()
        if src.parent != base or not src.is_file():
            return False
        with Image.open(src) as source:
            image = ImageOps.exif_transpose(source).convert("RGBA")
    else:
        image = source_image.convert("RGBA")
    settings = settings or dict(
        fit="contain" if contain else "cover", x=50, y=50, zoom=100
    )
    if grayscale:
        alpha = image.getchannel("A")
        image = ImageOps.grayscale(image).convert("RGBA")
        image.putalpha(alpha)
    w, h = box[2] - box[0], box[3] - box[1]
    ratios = (w / image.width, h / image.height)
    ratio = (
        (min(ratios) if settings["fit"] == "contain" else max(ratios))
        * settings["zoom"]
        / 100
    )
    image = image.resize(
        (max(1, round(image.width * ratio)), max(1, round(image.height * ratio))),
        Image.Resampling.LANCZOS,
    )
    viewport = Image.new("RGBA", (w, h), (0, 0, 0, 0 if source_image is not None else 255))
    viewport.alpha_composite(
        image,
        (
            round((w - image.width) * settings["x"] / 100),
            round((h - image.height) * settings["y"] / 100),
        ),
    )
    layer = Image.new("RGBA", canvas.size)
    layer.paste(viewport, (box[0], box[1]))
    if mask is not None:
        layer.putalpha(ImageChops.multiply(layer.getchannel("A"), mask))
    canvas.alpha_composite(layer)
    return True


def photo(canvas, data, root, role, box, *, mask=None, grayscale=False):
    source_image = None
    path = image_roles(data).get(role)
    if not path and role in ("ideology", "focus"):
        from hoi4_icons import entry_for, icon_image
        entry = entry_for(data, role)
        if entry:
            source_image = icon_image(entry["id"])
    return picture(
        canvas,
        root,
        path,
        box,
        settings=crop_settings(data, role),
        mask=mask,
        grayscale=grayscale,
        source_image=source_image,
    )


def party_data(raw):
    from PIL import ImageColor
    from pillow_renderer import PARLIAMENT_PALETTE

    parties = []
    for line in str(raw or "").splitlines():
        if not line.strip():
            continue
        if "|" in line or ";" in line:
            parts = [x.strip() for x in re.split(r"[|;]", line, maxsplit=2)]
        else:
            match = re.fullmatch(r"\s*(.+?)\s*,\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)%?)\s*(?:,\s*(.+))?\s*", line)
            if not match:
                match = re.fullmatch(r"\s*(.+?)\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+)%?)\s*(#[\da-fA-F]+|[A-Za-z]+|rgba?\(.*\))?\s*", line)
            parts = list(match.groups()) if match else []
        if len(parts) not in (2, 3) or not parts[0]:
            raise ValueError('Партии: каждая строка как "ЛПК, 43, rgb(243, 190, 32)"')
        name, value = parts[:2]
        color = (parts[2] if len(parts) == 3 else None) or PARLIAMENT_PALETTE[len(parties) % len(PARLIAMENT_PALETTE)]
        try:
            value = float(value.replace("%", "").replace(",", "."))
            rgba = re.fullmatch(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*\d+(?:\.\d+)?\s*\)", color, re.I)
            channels = tuple(int(rgba.group(i)) for i in (1, 2, 3)) if rgba else ImageColor.getrgb(color)
            if any(c < 0 or c > 255 for c in channels[:3]):
                raise ValueError
            color = "#%02X%02X%02X" % channels[:3]
            if not math.isfinite(value) or value <= 0:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError(
                "В долях партий нужны положительное число и цвет: #ffcc00, rgb(255, 204, 0) или yellow"
            ) from None
        parties.append((name, value, color))
    if len(parties) > 12:
        raise ValueError("На диаграмме помещается до 12 партий")
    return parties


def chart(canvas, raw, box, style):
    parties = party_data(raw)
    if not parties:
        return
    # Relative shares stay finite even for very large numeric values.
    largest = max(p[1] for p in parties)
    total = sum(p[1] / largest for p in parties)
    # Draw separately: Pillow's inclusive pieslice box used to paint one pixel
    # beyond the PSD aperture and over the surrounding bezel.
    scale = 4
    layer = Image.new("RGBA", (canvas.width * scale, canvas.height * scale))
    draw = ImageDraw.Draw(layer)
    bounds = (box[0]*scale, box[1]*scale, box[2]*scale-1, box[3]*scale-1)
    start = -90
    for _, value, color in parties:
        end = start + 360 * (value / largest) / total
        draw.pieslice(bounds, start, end, fill=color)
        start = end
    layer = layer.resize(canvas.size, Image.Resampling.LANCZOS)
    mask = asset(style + "_chart_mask", 2 if style == "tfr" else 1).convert("L")
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), mask))
    canvas.alpha_composite(layer)


def state_card(data, root, style):
    factor = 2 if style == "tfr" else 1
    foreground = asset(style + "_state_front", factor).convert("RGBA")
    canvas = Image.new("RGBA", foreground.size, "black")
    if style == "tno":
        boxes = dict(
            flag=(36, 12, 184, 104),
            portrait=(12, 120, 205, 380),
            title=(356, 15, 739, 47),
            alliance=(356, 48, 739, 75),
            leader=(356, 77, 739, 109),
            party=(389, 142, 837, 187),
            ideology=(389, 184, 837, 226),
            elections=(389, 226, 837, 263),
            focus=(399, 280, 827, 344),
            chart=(242, 139, 346, 243),
            icon=(225, 15, 331, 106),
            alliance_icon=(746, 15, 837, 105),
            focus_icon=(228, 270, 359, 374),
        )
    else:
        boxes = dict(
            flag=(28, 10, 101, 59),
            portrait=(12, 104, 119, 247),
            title=(212, 4, 405, 22),
            alliance=(212, 23, 405, 40),
            leader=(212, 42, 405, 61),
            party=(228, 115, 458, 133),
            ideology=(228, 133, 458, 151),
            elections=(228, 151, 458, 172),
            focus=(241, 196, 439, 229),
            chart=(140, 114, 192, 166),
            icon=(137, 5, 192, 61),
            alliance_icon=(411, 8, 461, 58),
            focus_icon=(128, 185, 200, 240),
        )
    boxes = {k: scaled(v, factor) for k, v in boxes.items()}
    # Image windows are behind the original bezels; the flag uses its PSD alpha.
    flag_mask = asset("tno_flag_mask") if style == "tno" else None
    photo(canvas, data, root, "flag", boxes["flag"], mask=flag_mask)
    portrait_mask = asset("tno_portrait_mask") if style == "tno" else None
    photo(canvas, data, root, "portrait", boxes["portrait"], mask=portrait_mask)
    canvas.alpha_composite(foreground)
    if style == "tno":
        canvas.alpha_composite(asset("tno_flag_glass"))
    # Icons belong to their original PSD cells, not to each other's slots.
    for role, key in (
        ("ideology", "icon"),
        ("alliance", "alliance_icon"),
        ("focus", "focus_icon"),
    ):
        photo(canvas, data, root, role, boxes[key])
    if style == "tno":
        # Native base below the sectors, clipped PSD shadows above them.
        canvas.alpha_composite(asset("tno_chart_front"))
        chart(canvas, data.get("parties"), boxes["chart"], style)
        canvas.alpha_composite(asset("tno_chart_effects"))
    else:
        chart(canvas, data.get("parties"), boxes["chart"], style)
        canvas.alpha_composite(asset("tfr_chart_front", factor))
    for key, field, default in (
        ("title", "country_name", data.get("title", "")),
        ("alliance", "alliance", ""),
        ("leader", "leader", ""),
        ("party", "ruling_party", ""),
        ("ideology", "ideology", ""),
        ("elections", "elections", ""),
        ("focus", "focus", "Фокус не выбран"),
    ):
        text_box(
            canvas,
            data.get(field) or default,
            boxes[key],
            style,
            STATE_TEXT_SIZES[style][key],
            field,
            minimum=14,
            align="center" if key == "focus" else "left",
            role="title" if style == "tno" and key in ("party", "ideology", "elections", "focus") else "body",
        )
    return canvas


def event_card(data, root, style):
    factor = 2 if style == "tfr" else 1
    foreground = asset(style + "_event_front", factor).convert("RGBA")
    canvas = Image.new("RGBA", foreground.size, "black")
    mask = asset(style + "_event_mask", factor).convert("L")
    # Bounding boxes are measured from the actual image placeholders in the PSD.
    box = (8, 91, 1040, 795) if style == "tno" else scaled((4, 18, 521, 368), factor)
    photo(canvas, data, root, "event", box, mask=mask, grayscale=style == "tno")
    if style == "tno":
        canvas.alpha_composite(asset("tno_event_effects"))
    # TFR's real gradient, quote panel and button are ONE partially transparent
    # foreground. Compositing this last preserves their original alpha and shape.
    canvas.alpha_composite(foreground)
    if style == "tno":
        title = (33, 16, 1017, 72)
        body = (85, 553, 1024, 781)
        buttons = [
            ("normal", (328, 821, 723, 878)),
            ("large", (288, 821, 763, 878)),
            ("wide", (248, 821, 803, 878)),
            ("full", (38, 821, 1014, 878)),
        ]
        button_text = str(data.get("button_text") or "")
        chosen = buttons[-1]
        for name, bounds in buttons:
            if font(style, EVENT_BUTTON_SIZE[style]).getlength(button_text) <= bounds[2] - bounds[0] - 36:
                chosen = (name, bounds)
                break
        canvas.alpha_composite(asset("tno_button_" + chosen[0]))
        b = chosen[1]
        button = (b[0] + 18, b[1] + 5, b[2] - 18, b[3] - 5)
    else:
        title = scaled((65, 10, 462, 33), factor)
        body = scaled((112, 255, 413, 325), factor)
        button = scaled((200, 344, 336, 362), factor)
    text_box(
        canvas,
        data.get("event_title") or data.get("title"),
        title,
        style,
        20 if style == "tfr" else 34,
        "Заголовок суперевента",
        role="title",
        align="center",
        minimum=16 if style == "tfr" else 18,
    )
    body_value = str(data.get("body") or "")
    if data.get("quote_author"):
        body_value += "\n- " + str(data["quote_author"])
    text_box(
        canvas,
        body_value,
        body,
        style,
        EVENT_QUOTE_SIZE[style],
        "Текст или цитата",
        align="right" if style == "tno" else "center",
        minimum=16,
        valign="top" if style == "tfr" else "center",
        line_height=29 if style == "tfr" else None,
    )
    text_box(
        canvas,
        data.get("button_text"),
        button,
        style,
        EVENT_BUTTON_SIZE[style],
        "Надпись на кнопке",
        align="center",
        minimum=14,
    )
    return canvas


def news_card(data, root):
    from hoi4_limits import NEWS_FIELDS, NEWS_BODY_LINE_HEIGHT, news_data_error

    error = news_data_error("superevent", data)
    if error:
        raise Hoi4TextOverflow(error)
    foreground = asset("tno_news_front").convert("RGBA")
    canvas = Image.new("RGBA", foreground.size, "black")
    photo(
        canvas,
        data,
        root,
        "news",
        (22, 143, 223, 652),
        mask=asset("tno_news_mask"),
        grayscale=True,
    )
    canvas.alpha_composite(asset("tno_news_effects"))
    canvas.alpha_composite(foreground)
    if not data.get("newspaper_name"):
        canvas.alpha_composite(asset("tno_news_masthead"))
    for key, (label, limit, box, size, minimum) in NEWS_FIELDS.items():
        # Title is a private card name. Never silently use a long card name
        # as a newspaper headline and bypass the headline input limit.
        value = data.get(key)
        text_box(
            canvas,
            value,
            box,
            "tno",
            size,
            label,
            role="news",
            align="left" if key in ("news_body", "news_date") else "center",
            minimum=minimum,
            fill="#25251f",
            valign="top" if key == "news_body" else "center",
            line_height=NEWS_BODY_LINE_HEIGHT if key == "news_body" else None,
        )
    return canvas


def render_hoi4(page, root, output, quality="high"):
    style = style_for(page)
    data = dict(page.data or {})
    data.setdefault("title", page.title)
    data["hoi4_style"] = style
    mode = hoi4_mode(data)
    if mode == "news" and style != "tno":
        raise ValueError("Газета доступна в TNO. Выбери оформление TNO")
    if mode == "state":
        result = state_card(data, root, style)
    elif mode == "event":
        result = event_card(data, root, style)
    elif mode == "news":
        result = news_card(data, root)
    else:
        state = state_card(data, root, style)
        event = event_card(data, root, style)
        if style == "tno":
            result = Image.new("RGBA", (1920, 1080), "black")
            result.alpha_composite(state, (0, 1))
            result.alpha_composite(event, (868, 99))
            result.alpha_composite(news_card(data, root), (244, 397))
        else:
            result = Image.new("RGBA", (2006, 1128), "black")
            result.alpha_composite(state, (0, 0))
            result.alpha_composite(event, (954, 374))
        # Both combined layouts leave this corner black and clear of cards.
        ImageDraw.Draw(result).text(
            (32, result.height - 48), "Aurelia INFOBOX",
            font=font(style, 24), fill="#737b80",
        )
    if quality == "standard" and result.width > 1280:
        result.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
    elif quality == "ultra":
        result = result.resize(
            (result.width * 2, result.height * 2), Image.Resampling.LANCZOS
        )
    # Publish only a complete file; previews may be opened as soon as returned.
    import os
    from uuid import uuid4

    destination = Path(output)
    temporary = destination.with_name(destination.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("wb") as stream:
            result.convert("RGB").save(stream, "PNG", compress_level=6)
            stream.flush()
            os.fsync(stream.fileno())
        with Image.open(temporary) as check:
            check.verify()
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
