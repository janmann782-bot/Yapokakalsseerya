"""HOI4 cards assembled from the author's PSD artwork. No Photoshop at runtime."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from media import page_images
from templates import hoi4_mode

ASSETS = Path(__file__).resolve().parent / "assets" / "hoi4"
LAYOUT_VERSION = 1
INK = "#dbe4e5"


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
        roles["event"] = "Картинка события"
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
        step = ascent + descent + max(2, px // 6)
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


def picture(canvas, root, path, box, *, grayscale=False, contain=False):
    if not path:
        return False
    base = Path(root).resolve()
    src = (base / str(path)).resolve()
    # Media must stay in this bot's work directory, same as ordinary cards.
    if src.parent != base or not src.is_file():
        return False
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGBA")
        if grayscale:
            alpha = im.getchannel("A")
            im = ImageOps.grayscale(im).convert("RGBA")
            im.putalpha(alpha)
        size = (box[2] - box[0], box[3] - box[1])
        im = (
            ImageOps.contain(im, size, Image.Resampling.LANCZOS)
            if contain
            else ImageOps.fit(im, size, Image.Resampling.LANCZOS)
        )
        canvas.alpha_composite(
            im,
            (box[0] + (size[0] - im.width) // 2, box[1] + (size[1] - im.height) // 2),
        )
    return True


def party_data(raw):
    parties = []
    for line in str(raw or "").splitlines():
        if not line.strip():
            continue
        parts = [x.strip() for x in line.split("|")]
        if len(parts) != 3:
            raise ValueError('Доли партий: пиши каждую строку как "ЛПК | 40 | #ffcc00"')
        name, value, color = parts
        try:
            value = float(value.replace("%", "").replace(",", "."))
            from PIL import ImageColor

            ImageColor.getrgb(color)
            if not math.isfinite(value) or value <= 0:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError(
                "В долях партий нужны положительное число и цвет вроде #ffcc00"
            ) from None
        parties.append((name, value, color))
    if len(parties) > 12:
        raise ValueError("На диаграмме помещается до 12 партий")
    return parties


def chart(canvas, raw, box, style):
    draw = ImageDraw.Draw(canvas)
    parties = party_data(raw)
    draw.ellipse(box, fill="#32393b", outline="#77888a", width=2)
    if not parties:
        text_box(canvas, "?", box, style, 34, "Диаграмма", align="center")
        return
    start = -90
    total = sum(p[1] for p in parties)
    for _, value, color in parties:
        end = start + 360 * value / total
        draw.pieslice(box, start, end, fill=color, outline="#26282b", width=1)
        start = end


def state_card(data, root, style):
    # TFR's source panel is 470px wide; render at 2x so Cyrillic stays readable.
    factor = 2 if style == "tfr" else 1
    with Image.open(ASSETS / f"{style}_state.png") as src:
        canvas = src.convert("RGBA").resize(
            (src.width * factor, src.height * factor), Image.Resampling.NEAREST
        )
    roles = image_roles(data)
    if style == "tno":
        boxes = dict(
            flag=(42, 22, 177, 98),
            portrait=(17, 125, 198, 374),
            title=(353, 15, 838, 47),
            alliance=(353, 47, 838, 75),
            leader=(353, 77, 838, 109),
            party=(389, 143, 837, 188),
            ideology=(389, 185, 837, 225),
            elections=(389, 226, 837, 263),
            focus=(401, 282, 824, 345),
            chart=(241, 138, 347, 244),
            icon=(224, 19, 321, 103),
            alliance_icon=(230, 276, 355, 369),
        )
        size = 25
    else:
        boxes = dict(
            flag=(30, 20, 190, 108),
            portrait=(28, 214, 230, 484),
            title=(420, 9, 917, 48),
            alliance=(420, 48, 917, 83),
            leader=(420, 84, 917, 122),
            party=(450, 223, 913, 268),
            ideology=(450, 266, 913, 307),
            elections=(450, 307, 913, 350),
            focus=(474, 392, 879, 458),
            chart=(276, 225, 389, 338),
            icon=(272, 13, 381, 118),
            alliance_icon=(260, 365, 400, 474),
        )
        size = 23
        # These labels are baked into the PSD's Base layer; localize them.
        draw = ImageDraw.Draw(canvas)
        for box, label in [
            ((32, 142, 449, 190), "Дипломатия"),
            ((492, 142, 901, 190), "Сведения"),
        ]:
            draw.rectangle(box, fill="#171a1c")
            text_box(canvas, label, box, style, 20, label, align="center")
    for role, key in [
        ("flag", "flag"),
        ("portrait", "portrait"),
        ("ideology", "icon"),
        ("alliance", "alliance_icon"),
    ]:
        picture(
            canvas,
            root,
            roles.get(role),
            boxes[key],
            contain=role in ("flag", "ideology", "alliance"),
        )
    if not roles.get("portrait"):
        # A missing portrait is neutral, never a real person from the template.
        b = boxes["portrait"]
        ImageDraw.Draw(canvas).rectangle(b, fill="#202629")
        text_box(
            canvas,
            "Нет портрета",
            (b[0] + 8, b[1], b[2] - 8, b[3]),
            style,
            18,
            "Портрет",
            align="center",
        )
    chart(canvas, data.get("parties"), boxes["chart"], style)
    for key, field, default in [
        ("title", "country_name", data.get("title", "")),
        ("alliance", "alliance", "Альянс не указан"),
        ("leader", "leader", "Лидер не указан"),
        ("party", "ruling_party", "Партия не указана"),
        ("ideology", "ideology", "Идеология не указана"),
        ("elections", "elections", "Выборы не указаны"),
        ("focus", "focus", "Фокус не выбран"),
    ]:
        text_box(
            canvas,
            data.get(field) or default,
            boxes[key],
            style,
            size,
            field,
            align="center" if key == "focus" else "left",
            role="title" if style == "tno" and key == "title" else "body",
        )
    # Custom focus icon stays separate from the country's portrait and flag.
    if roles.get("focus"):
        focus_box = (227, 270, 360, 373) if style == "tno" else (270, 370, 390, 480)
        picture(canvas, root, roles["focus"], focus_box, contain=True)
    return canvas


def event_card(data, root, style):
    with Image.open(ASSETS / f"{style}_event.png") as im:
        factor = 2 if style == "tfr" else 1
        canvas = im.convert("RGBA").resize(
            (im.width * factor, im.height * factor), Image.Resampling.NEAREST
        )
    roles = image_roles(data)
    if style == "tno":
        img = (9, 94, 1040, 793)
        title = (33, 17, 1017, 69)
        body = (65, 550, 985, 770)
        button = (345, 829, 705, 877)
    else:
        img = (16, 73, 1039, 688)
        title = (115, 13, 945, 65)
        body = (202, 500, 850, 658)
        button = (397, 699, 685, 739)
    original = canvas.copy()
    has_photo = picture(canvas, root, roles.get("event"), img, grayscale=style == "tno")
    if has_photo and style == "tfr":
        from PIL import ImageChops

        region = canvas.crop(img).convert("RGB")
        gradient = original.crop((20, 80, 1020, 470)).resize(region.size).convert("RGB")
        mixed = Image.blend(region, ImageChops.screen(region, gradient), 0.45)
        canvas.paste(mixed, (img[0], img[1]))
    # Preserve original PSD scanlines, coloring and borders above the image.
    draw = ImageDraw.Draw(canvas)
    shade = Image.new("RGBA", canvas.size)
    sd = ImageDraw.Draw(shade)
    for y in range(img[1], img[3], 3):
        sd.line((img[0], y, img[2], y), fill=(0, 20, 24, 32 if style == "tno" else 14))
    if style == "tno":
        sd.rectangle(img, fill=(0, 45, 49, 42))
    if data.get("body") or data.get("quote_author"):
        sd.rectangle(body, fill=(0, 0, 0, 172))
    canvas = Image.alpha_composite(canvas, shade)
    # Restore the border of the quotation panel for TFR.
    if style == "tfr":
        draw = ImageDraw.Draw(canvas)
        draw.rectangle(body, outline="#af75b9", width=3)
    title_value = data.get("event_title") or data.get("title")
    text_box(
        canvas,
        title_value,
        title,
        style,
        34,
        "Заголовок события",
        role="title",
        align="center",
        minimum=18,
    )
    body_value = str(data.get("body") or "")
    if data.get("quote_author"):
        body_value += "\n- " + str(data["quote_author"])
    text_box(
        canvas,
        body_value,
        (body[0] + 16, body[1] + 8, body[2] - 16, body[3] - 8),
        style,
        28,
        "Текст или цитата",
        align="right" if style == "tno" else "center",
        minimum=16,
    )
    text_box(
        canvas,
        data.get("button_text"),
        button,
        style,
        24,
        "Надпись на кнопке",
        align="center",
        minimum=14,
    )
    return canvas


def news_card(data, root):
    canvas = Image.open(ASSETS / "tno_news.png").convert("RGBA")
    # Cover the sample masthead with the paper's own texture, not a flat rectangle.
    if data.get("newspaper_name"):
        patch = canvas.crop((230, 120, 580, 195)).resize((475, 75))
        canvas.paste(patch, (96, 20))
        text_box(
            canvas,
            data["newspaper_name"],
            (99, 24, 571, 91),
            "tno",
            34,
            "Название газеты",
            role="news",
            align="center",
            minimum=16,
            fill="#25251f",
        )
    text_box(
        canvas,
        data.get("news_title") or data.get("title"),
        (37, 103, 584, 143),
        "tno",
        23,
        "Заголовок газеты",
        role="news",
        align="center",
        minimum=14,
        fill="#25251f",
    )
    picture(
        canvas, root, image_roles(data).get("news"), (26, 146, 222, 648), grayscale=True
    )
    text_box(
        canvas,
        data.get("news_body"),
        (237, 161, 578, 580),
        "tno",
        20,
        "Текст газеты",
        role="news",
        minimum=14,
        fill="#25251f",
        valign="top",
    )
    text_box(
        canvas,
        data.get("news_date"),
        (241, 581, 578, 618),
        "tno",
        16,
        "Дата газеты",
        role="news",
        minimum=12,
        fill="#25251f",
    )
    text_box(
        canvas,
        data.get("news_button"),
        (242, 622, 583, 666),
        "tno",
        18,
        "Подпись газеты",
        role="news",
        align="center",
        fill="#25251f",
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
    if quality == "standard" and result.width > 1280:
        result.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
    elif quality == "ultra":
        result = result.resize(
            (result.width * 2, result.height * 2), Image.Resampling.LANCZOS
        )
    result.convert("RGB").save(output, "PNG", compress_level=6)
    return Path(output)
