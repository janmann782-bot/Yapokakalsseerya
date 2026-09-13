from __future__ import annotations

from pathlib import Path
import math
import re

from PIL import Image, ImageDraw, ImageFont, ImageOps

from media import battle_image_groups, image_caption, map_image_caption, map_images, page_images, parliament_image_assets
from models import Page
from templates import Field, Template, get_template
from themes import Theme, get_theme
from fonts_catalog import resolve_font_files, resolve_user_font


PILLOW_SCALE = {"standard": 3.0, "high": 3.5, "ultra": 4.0}

_ACTIVE_FONT_REG: str | None = None
_ACTIVE_FONT_BOLD: str | None = None




def _resolve_kind_label(tpl: Template, data: dict) -> str:
    value = str(data.get("card_type_label") or "").strip()
    if not value:
        return tpl.label.upper()
    low = value.casefold().replace("ё", "е").strip()
    if low in {"none", "hide", "hidden", "скрыть", "убрать", "нет", "off", "-"}:
        return ""
    return value.upper()


def _font(theme: Theme, size: int, bold: bool = False, heading: bool = False):
    if _ACTIVE_FONT_REG:
        path = _ACTIVE_FONT_BOLD if bold and _ACTIVE_FONT_BOLD else _ACTIVE_FONT_REG
        try:
            return ImageFont.truetype(path, size), ImageFont.truetype(path, size)
        except Exception:
            pass
    here = Path(__file__).resolve().parent
    if theme.key == "aurelia":
        fallback_name = "LiberationMono-Bold.ttf" if bold else "LiberationMono-Regular.ttf"
        fallback = _load_font(here, fallback_name, size)
        isaac = here / "ISAACFONTDESCRIPTIONENGRUS-FILL_0.TTF"
        if isaac.is_file():
            return ImageFont.truetype(str(isaac), size), fallback
        return fallback

    if heading:
        if theme.key in {"light", "dark"}:
            libertine = Path(
                "/usr/share/fonts/opentype/linux-libertine/"
                + ("LinLibertine_RB.otf" if bold else "LinLibertine_R.otf")
            )
            if libertine.is_file():
                return ImageFont.truetype(str(libertine), size)
        name = "LiberationSerif-Bold.ttf" if bold else "LiberationSerif-Regular.ttf"
    else:
        name = "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf"
    return _load_font(here, name, size)


def _load_font(here: Path, name: str, size: int):
    paths = [
        here / name,
        Path("/usr/share/fonts/truetype/liberation") / name,
        Path("/usr/local/share/fonts") / name,
        Path("C:/Windows/Fonts") / name,
    ]
    for p in paths:
        if p.is_file():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size=size)


def _font_runs(text: str, font):
    if not isinstance(font, tuple):
        return [(text, font)]

    primary, fallback = font
    out = []
    buf = ""
    cur = None
    extra = "—–…«»№ "
    for ch in text:
        n = ord(ch)
        use_primary = 32 <= n <= 126 or 0x0410 <= n <= 0x044F or n in {0x0401, 0x0451} or ch in extra
        f = primary if use_primary else fallback
        if cur is not None and f is not cur:
            out.append((buf, cur))
            buf = ""
        buf += ch
        cur = f
    if buf:
        out.append((buf, cur))
    return out or [("", primary)]


def _size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    width = 0
    height = 0
    for s, f in _font_runs(text or "Ag", font):
        box = draw.textbbox((0, 0), s, font=f)
        width += box[2] - box[0]
        height = max(height, box[3] - box[1])
    return width, height


def _split_word(draw: ImageDraw.ImageDraw, word: str, font, max_w: int) -> list[str]:
    out = []
    s = ""
    for ch in word:
        x = s + ch
        if s and _size(draw, x, font)[0] > max_w:
            out.append(s)
            s = ch
        else:
            s = x
    if s:
        out.append(s)
    return out or [""]


def _wrap(draw: ImageDraw.ImageDraw, value: object, font, max_w: int) -> list[str]:
    text = "\n".join(str(x) for x in value) if isinstance(value, (list, tuple)) else str(value)
    out = []
    for raw in text.split("\n"):
        words = raw.split()
        if not words:
            out.append("")
            continue
        line = ""
        for word in words:
            parts = _split_word(draw, word, font, max_w)
            for part in parts:
                x = part if not line else f"{line} {part}"
                if line and _size(draw, x, font)[0] > max_w:
                    out.append(line)
                    line = part
                else:
                    line = x
        if line:
            out.append(line)
    return out or [""]


def _line_h(draw: ImageDraw.ImageDraw, font) -> int:
    return int(_size(draw, "Аg", font)[1] * 1.42)


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    xy: tuple[int, int],
    font,
    fill: str,
    line_h: int,
    width: int | None = None,
    align: str = "left",
) -> None:
    x, y = xy
    for line in lines:
        xx = x
        if width and align != "left":
            w = _size(draw, line, font)[0]
            xx = x + (width - w if align == "right" else (width - w) // 2)
        for s, f in _font_runs(line, font):
            draw.text((xx, y), s, font=f, fill=fill)
            xx += _size(draw, s, f)[0]
        y += line_h


def _header(w: int, s: float, tpl: Template, page: Page, theme: Theme, right_reserve: int = 0, min_height: int = 0) -> Image.Image:
    tmp = Image.new("RGB", (w, 10), theme.panel)
    draw = ImageDraw.Draw(tmp)
    kind_font = _font(theme, max(9, int(11 * s)), bold=True)
    title_font = _font(theme, max(18, int(23 * s)), bold=theme.key not in {"light", "dark"}, heading=True)
    sub_font = _font(theme, max(10, int(13 * s)))
    pad_x = int(10 * s)
    pad_y = int(8 * s)
    title = page.data.get("title") or page.title or "Без названия"
    subtitle = page.data.get(tpl.subtitle_key, "") if tpl.subtitle_key else ""
    kind = _resolve_kind_label(tpl, page.data)
    if theme.key in {"light", "dark"} and not str(page.data.get("card_type_label") or "").strip():
        kind = ""
    text_w = max(40, w - pad_x * 2 - max(0, right_reserve))
    title_w = max(40, w - pad_x * 2 - (max(0, right_reserve) * 2 if tpl.key == "parliament" else 0))
    kind_lines = _wrap(draw, kind, kind_font, text_w) if kind else []
    title_lines = _wrap(draw, title, title_font, title_w)
    sub_lines = _wrap(draw, subtitle, sub_font, text_w) if subtitle else []
    kh = _line_h(draw, kind_font)
    th = _line_h(draw, title_font)
    sh = _line_h(draw, sub_font)
    gap = max(2, int(3 * s))
    h = pad_y * 2 + len(title_lines) * th
    if kind_lines:
        h += len(kind_lines) * kh + gap
    if sub_lines:
        h += gap + len(sub_lines) * sh
    h = max(h, int(min_height or 0))

    img = Image.new("RGB", (w, h), theme.panel)
    draw = ImageDraw.Draw(img)
    y = pad_y
    if kind_lines:
        _draw_lines(draw, kind_lines, (pad_x, y), kind_font, theme.text_secondary, kh, text_w, "left" if tpl.key == "parliament" else "center")
        y += len(kind_lines) * kh + gap
    if tpl.key == "parliament":
        _draw_lines(draw, title_lines, (pad_x, y), title_font, theme.text, th, text_w, "left")
    else:
        _draw_lines(draw, title_lines, (pad_x, y), title_font, theme.text, th, text_w, "center")
    y += len(title_lines) * th
    if sub_lines:
        y += gap
        _draw_lines(draw, sub_lines, (pad_x, y), sub_font, theme.text, sh, text_w, "left" if tpl.key == "parliament" else "center")
    return img


def _media_path(value: object, root: Path) -> Path | None:
    if not value:
        return None
    raw = Path(str(value))
    p = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if p.parent != root or not p.name.startswith("media_") or not p.is_file():
        return None
    return p


def _picture(
    w: int,
    s: float,
    path: Path,
    caption: object,
    theme: Theme,
) -> Image.Image | None:
    try:
        src = ImageOps.exif_transpose(Image.open(path))
        src.load()
    except Exception:
        return None

    pad_x = int(8 * s)
    pad_y = int(6 * s)
    max_w = min(w - pad_x * 2, int(300 * s))
    max_h = int(360 * s)
    src.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    if src.mode in {"RGBA", "LA"}:
        base = Image.new("RGBA", src.size, theme.panel)
        base.alpha_composite(src.convert("RGBA"))
        src = base.convert("RGB")
    else:
        src = src.convert("RGB")

    cap_font = _font(theme, max(9, int(12 * s)))
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines = _wrap(tmp, caption, cap_font, min(w - pad_x * 2, int(320 * s))) if caption else []
    lh = _line_h(tmp, cap_font)
    cap_gap = int(4 * s) if lines else 0
    h = pad_y + src.height + cap_gap + len(lines) * lh + pad_y
    img = Image.new("RGB", (w, h), theme.panel)
    draw = ImageDraw.Draw(img)
    x = (w - src.width) // 2
    img.paste(src, (x, pad_y))
    if lines:
        _draw_lines(draw, lines, (pad_x, pad_y + src.height + cap_gap), cap_font, theme.text, lh, w - pad_x * 2, "center")
    return img


def _gallery(
    w: int,
    s: float,
    items: list[tuple[Path, str]],
    theme: Theme,
) -> Image.Image | None:
    blocks = []
    for path, caption in items:
        block = _picture(w, s, path, caption, theme)
        if block is not None:
            blocks.append(block)
    if not blocks:
        return None
    if len(blocks) == 1:
        return blocks[0]
    gap = max(1, int(2 * s))
    h = sum(b.height for b in blocks) + gap * (len(blocks) - 1)
    out = Image.new("RGB", (w, h), theme.panel)
    y = 0
    for i, block in enumerate(blocks):
        out.paste(block, (0, y))
        y += block.height
        if i + 1 < len(blocks):
            y += gap
    return out


def _battle_media_items(data: dict, root: Path):
    main_item, side1_items, side2_items, extra_items = battle_image_groups(data)

    def resolve(item):
        if not item:
            return None
        path = _media_path(item[0], root)
        if not path:
            return None
        return path, item[1]

    def resolve_list(items):
        out = []
        for path, caption in items:
            p = _media_path(path, root)
            if p:
                out.append((p, caption))
        return out

    return resolve(main_item), resolve_list(side1_items), resolve_list(side2_items), resolve_list(extra_items)


def _flag_thumb(path: Path, size: tuple[int, int], bg: str):
    try:
        src = ImageOps.exif_transpose(Image.open(path))
        src.load()
    except Exception:
        return None
    src = src.convert('RGB')
    src = ImageOps.fit(src, size, Image.Resampling.LANCZOS)
    base = Image.new('RGB', size, bg)
    base.paste(src, (0, 0))
    return base


def _battle_side_cells(w: int, s: float, left: object, right: object, theme: Theme, flags1: list[tuple[Path, str]], flags2: list[tuple[Path, str]]) -> Image.Image:
    """Compact Wikipedia-like conflict cells: both columns use flag-before-name rows."""
    col_w = w // 2
    pad_x = int(6 * s)
    pad_y = int(5 * s)
    font = _font(theme, max(10, int(13 * s)))
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lh = _line_h(tmp, font)
    flag_size = (max(20, int(26 * s)), max(13, int(17 * s)))
    gap = max(3, int(4 * s))
    row_gap = max(2, int(3 * s))

    def side_rows(value, flags):
        raw = value if value not in (None, "", []) else "—"
        if isinstance(raw, (list, tuple)):
            parts = [str(x).strip() for x in raw if str(x).strip()]
        else:
            parts = [ln.strip() for ln in str(raw).splitlines() if ln.strip()]
        if not parts:
            parts = ["—"]
        part_keys = {x.casefold().replace("ё", "е").strip() for x in parts}
        named = {}
        fallback = []
        for path, cap in flags:
            thumb = _flag_thumb(path, flag_size, theme.panel)
            if thumb is None:
                continue
            key = str(cap or "").casefold().replace("ё", "е").strip()
            if key and key in part_keys:
                named[key] = thumb
            else:
                fallback.append(thumb)
        fallback_slots = [i for i, x in enumerate(parts) if x.casefold().replace("ё", "е").strip() not in named]
        fallback_targets = set(fallback_slots[-len(fallback):]) if fallback else set()
        fallback_iter = iter(fallback)
        rows = []
        for i, part in enumerate(parts):
            key = part.casefold().replace("ё", "е").strip()
            thumb = named.get(key)
            if thumb is None and i in fallback_targets:
                thumb = next(fallback_iter, None)
            reserve = (thumb.width + gap) if thumb is not None else 0
            lines = _wrap(tmp, part, font, max(30, col_w - pad_x * 2 - reserve))
            rows.append((thumb, lines))
        return rows

    def rows_height(rows):
        total = 0
        for i, (thumb, lines) in enumerate(rows):
            total += max(thumb.height if thumb is not None else 0, len(lines) * lh, lh)
            if i + 1 < len(rows):
                total += row_gap
        return total

    left_rows = side_rows(left, flags1)
    right_rows = side_rows(right, flags2)
    h = max(rows_height(left_rows), rows_height(right_rows)) + pad_y * 2
    img = Image.new("RGB", (w, h), theme.panel)
    draw = ImageDraw.Draw(img)
    draw.line((col_w, 0, col_w, h), fill=theme.border, width=max(1, int(theme.border_width * s)))

    def paint(x0, rows):
        y = pad_y
        for thumb, lines in rows:
            row_h = max(thumb.height if thumb is not None else 0, len(lines) * lh, lh)
            x = x0 + pad_x
            if thumb is not None:
                fy = y + max(0, (row_h - thumb.height) // 2)
                img.paste(thumb, (x, fy))
                draw.rectangle((x, fy, x + thumb.width - 1, fy + thumb.height - 1), outline=theme.image_border, width=1)
                x += thumb.width + gap
            ty = y + max(0, (row_h - len(lines) * lh) // 2)
            _draw_lines(draw, lines, (x, ty), font, theme.text, lh, max(20, x0 + col_w - pad_x - x), "left")
            y += row_h + row_gap

    paint(0, left_rows)
    paint(col_w, right_rows)
    return img


def _battle_text_cells(w: int, s: float, left: object, right: object, theme: Theme) -> Image.Image:
    col_w = w // 2
    pad_x = int(6 * s)
    pad_y = int(5 * s)
    font = _font(theme, max(10, int(13 * s)))
    tmp = ImageDraw.Draw(Image.new('RGB', (1,1)))
    lh = _line_h(tmp, font)
    left_text = left if left not in (None, '', []) else '—'
    right_text = right if right not in (None, '', []) else '—'
    left_lines = _wrap(tmp, left_text, font, col_w - pad_x * 2)
    right_lines = _wrap(tmp, right_text, font, col_w - pad_x * 2)
    h = max(len(left_lines) * lh, len(right_lines) * lh) + pad_y * 2
    img = Image.new('RGB', (w, h), theme.panel)
    draw = ImageDraw.Draw(img)
    draw.line((col_w, 0, col_w, h), fill=theme.border, width=max(1, int(theme.border_width * s)))
    _draw_lines(draw, left_lines, (pad_x, pad_y), font, theme.text, lh)
    _draw_lines(draw, right_lines, (col_w + pad_x, pad_y), font, theme.text, lh)
    return img


def _battle_blocks(page: Page, root: Path, inner_w: int, s: float, theme: Theme):
    d = page.data
    blocks = []
    main, side1_flags, side2_flags, _extras = _battle_media_items(d, root)
    if main:
        path, caption = main
        pic = _picture(inner_w, s, path, caption, theme)
        if pic:
            blocks.append(pic)
    maps = []
    for value in map_images(d):
        media_path = _media_path(value, root)
        if media_path:
            maps.append((media_path, map_image_caption(d, value)))
    if maps:
        pic = _gallery(inner_w, s, maps, theme)
        if pic:
            blocks.append(pic)
    for label, key in (("Дата", "date"), ("Место", "place"), ("Итог", "result"), ("Территориальные изменения", "territorial_changes")):
        if d.get(key) not in (None, '', []):
            blocks.append(_row(inner_w, s, label, d[key], theme))
    if d.get('side_1') not in (None, '', []) or d.get('side_2') not in (None, '', []):
        blocks.append(_section_title(inner_w, s, 'Противники', theme))
        blocks.append(_battle_side_cells(inner_w, s, d.get('side_1'), d.get('side_2'), theme, side1_flags, side2_flags))
    for title, left_key, right_key in [
        ('Командующие', 'commander_1', 'commander_2'),
        ('Силы сторон', 'strength_1', 'strength_2'),
        ('Потери', 'losses_1', 'losses_2'),
    ]:
        if d.get(left_key) not in (None, '', []) or d.get(right_key) not in (None, '', []):
            blocks.append(_section_title(inner_w, s, title, theme))
            blocks.append(_battle_text_cells(inner_w, s, d.get(left_key), d.get(right_key), theme))
    if d.get('casualties_civilian') not in (None, '', []):
        blocks.append(_row(inner_w, s, 'Жертвы среди гражданских', d['casualties_civilian'], theme))
    return blocks


def _section_title(w: int, s: float, title: str, theme: Theme) -> Image.Image:
    font = _font(theme, max(11, int(14 * s)), bold=True)
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    pad_x = int(6 * s)
    pad_y = int(4 * s)
    lines = _wrap(tmp, title, font, w - pad_x * 2)
    lh = _line_h(tmp, font)
    img = Image.new("RGB", (w, pad_y * 2 + lh * len(lines)), theme.section_bg)
    draw = ImageDraw.Draw(img)
    _draw_lines(draw, lines, (pad_x, pad_y), font, theme.section_text, lh, w - pad_x * 2, "center")
    return img


def _row(w: int, s: float, label: object, value: object, theme: Theme, alternate: bool = False) -> Image.Image:
    label_w = int(w * 0.38)
    pad_x = int(5 * s)
    pad_y = int(3 * s)
    label_font = _font(theme, max(10, int(13 * s)), bold=True)
    value_font = _font(theme, max(10, int(13 * s)))
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    left = _wrap(tmp, label, label_font, label_w - pad_x * 2)
    right = _wrap(tmp, value, value_font, w - label_w - pad_x * 2)
    lh1 = _line_h(tmp, label_font)
    lh2 = _line_h(tmp, value_font)
    h = max(len(left) * lh1, len(right) * lh2) + pad_y * 2
    img = Image.new("RGB", (w, h), theme.panel)
    draw = ImageDraw.Draw(img)
    _draw_lines(draw, left, (pad_x, pad_y), label_font, theme.text, lh1)
    _draw_lines(draw, right, (label_w + pad_x, pad_y), value_font, theme.text, lh2)
    return img


def _side_rows(w: int, s: float, fields: list[Field], data: dict, theme: Theme) -> Image.Image:
    col_w = w // 2
    pad_x = int(6 * s)
    pad_y = int(5 * s)
    gap = int(5 * s)
    label_font = _font(theme, max(9, int(12 * s)), bold=True)
    value_font = _font(theme, max(10, int(13 * s)))
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lh1 = _line_h(tmp, label_font)
    lh2 = _line_h(tmp, value_font)
    cols = [[], []]
    heights = [pad_y, pad_y]
    for col in (1, 2):
        for f in fields:
            value = data.get(f.key)
            if f.column != col or value in (None, "", []):
                continue
            labels = _wrap(tmp, f.label, label_font, col_w - pad_x * 2)
            values = _wrap(tmp, value, value_font, col_w - pad_x * 2)
            h = len(labels) * lh1 + int(1 * s) + len(values) * lh2
            cols[col - 1].append((labels, values, h))
            heights[col - 1] += h + gap
    h = max(max(heights), int(28 * s)) + pad_y
    img = Image.new("RGB", (w, h), theme.panel)
    draw = ImageDraw.Draw(img)
    draw.line((col_w, 0, col_w, h), fill=theme.border, width=max(1, int(theme.border_width * s)))
    for i, items in enumerate(cols):
        y = pad_y
        x = i * col_w + pad_x
        for labels, values, _item_h in items:
            _draw_lines(draw, labels, (x, y), label_font, theme.text, lh1)
            y += len(labels) * lh1 + int(1 * s)
            _draw_lines(draw, values, (x, y), value_font, theme.text, lh2)
            y += len(values) * lh2 + gap
    return img


def _description(w: int, s: float, value: object, theme: Theme) -> Image.Image:
    font = _font(theme, max(10, int(14 * s)))
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    pad_x = int(7 * s)
    pad_y = int(6 * s)
    lines = _wrap(tmp, value, font, w - pad_x * 2)
    lh = _line_h(tmp, font)
    img = Image.new("RGB", (w, pad_y * 2 + len(lines) * lh), theme.panel)
    _draw_lines(ImageDraw.Draw(img), lines, (pad_x, pad_y), font, theme.text, lh)
    return img


PARLIAMENT_PALETTE = (
    "#5B8FF9", "#61DDAA", "#65789B", "#F6BD16", "#7262FD",
    "#78D3F8", "#9661BC", "#F6903D", "#008685", "#F08BB4",
)


def _norm_key(value: object) -> str:
    return str(value or "").casefold().replace("ё", "е").strip()


def _parse_int_value(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    digits = ''.join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def _safe_color(value: object, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if raw.startswith('#') and len(raw) in {4, 7}:
        body = raw[1:]
        if all(ch in '0123456789abcdefABCDEF' for ch in body):
            return raw
    m = re.match(r'^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*([0-9.]+))?\s*\)$', raw, re.I)
    if m:
        r = max(0, min(255, int(m.group(1))))
        g = max(0, min(255, int(m.group(2))))
        b = max(0, min(255, int(m.group(3))))
        return f'#{r:02X}{g:02X}{b:02X}'
    named = raw.lower()
    return raw if named in {'red', 'green', 'blue', 'yellow', 'orange', 'purple', 'pink', 'gray', 'grey', 'black', 'white', 'brown'} else fallback


def _parse_parliament_parties(value: object, total_seats: int | None = None) -> tuple[list[dict], int]:
    parties: list[dict] = []
    lines = []
    if isinstance(value, (list, tuple)):
        lines = [str(x).strip() for x in value if str(x).strip()]
    else:
        lines = [ln.strip() for ln in str(value or '').splitlines() if ln.strip()]
    for idx, raw in enumerate(lines):
        name = ''
        seats = None
        color = ''
        if '|' in raw or ';' in raw:
            parts = [p.strip() for p in re.split(r'\s*[|;]\s*', raw) if p.strip()]
            if len(parts) >= 2:
                name = parts[0]
                seats = _parse_int_value(parts[1])
                color = parts[2] if len(parts) >= 3 else ''
        else:
            m = re.match(r'^\s*(.+?)\s*,\s*(\d+)\s*(?:,\s*(.+))?$', raw)
            if m:
                name = m.group(1).strip()
                seats = int(m.group(2))
                color = (m.group(3) or '').strip()
            else:
                m = re.match(r'^(.*?)\s+(\d+)\s*(#[0-9A-Fa-f]{3,6}|[A-Za-z]+|rgba?\(.*\))?\s*$', raw)
                if m:
                    name = m.group(1).strip()
                    seats = int(m.group(2))
                    color = (m.group(3) or '').strip()
        if not name or not seats or seats <= 0:
            continue
        parties.append({
            'name': name,
            'seats': seats,
            'color': _safe_color(color, PARLIAMENT_PALETTE[idx % len(PARLIAMENT_PALETTE)]),
        })
    total = total_seats or sum(int(x['seats']) for x in parties)
    return parties, total


def _seat_shape(value: object) -> str:
    low = str(value or '').strip().casefold()
    return 'square' if low.startswith('квад') or 'square' in low or 'rect' in low else 'circle'


def _max_arc_seats(radius: float, pitch: float) -> int:
    """Maximum seat centers on a semicircle with at least ``pitch`` distance."""
    if radius <= 0 or pitch <= 0:
        return 1
    ratio = min(1.0, pitch / (2.0 * radius))
    if ratio >= 1.0:
        return 1
    angle = 2.0 * math.asin(ratio)
    return max(1, int(math.floor(math.pi / angle)))


def _hemicycle_layout(total: int, s: float) -> tuple[list[int], float, float, float, int, int]:
    """Build non-overlapping concentric semicircle rows.

    Row count grows until the exact chord distance between neighbouring seats is
    larger than the seat diameter plus a visible gap. No overflow is ever dumped
    into the outer row, which was the cause of seats overlapping on 200+ chambers.
    """
    if total <= 0:
        return [], 26 * s, 13 * s, 4 * s, int(132 * s), int(111 * s)

    if total <= 60:
        seat_r, min_rows = 5.1 * s, 4
    elif total <= 110:
        seat_r, min_rows = 4.5 * s, 5
    elif total <= 170:
        seat_r, min_rows = 3.9 * s, 6
    elif total <= 280:
        seat_r, min_rows = 3.2 * s, 7
    else:
        seat_r, min_rows = 2.9 * s, 8

    gap = 1.8 * s
    # Conservative spacing also guarantees axis-aligned square seats never touch.
    pitch = 2.0 * seat_r * math.sqrt(2.0) + gap
    inner_r = 24.0 * s
    step = max(10.8 * s, pitch + 1.4 * s)

    rows = min_rows
    while rows < 24:
        capacities = [
            _max_arc_seats(inner_r + step * i, pitch)
            for i in range(rows)
        ]
        if sum(capacities) >= total:
            break
        rows += 1

    capacities = [
        _max_arc_seats(inner_r + step * i, pitch)
        for i in range(rows)
    ]

    # Distribute proportionally to row capacity, then fill remaining free slots
    # from the outside in. Every row always stays under its geometric capacity.
    cap_sum = max(1, sum(capacities))
    counts = [max(1, min(cap, int(total * cap / cap_sum))) for cap in capacities]

    # If mandatory one-per-row pushed us above total, remove from inner rows first.
    while sum(counts) > total:
        changed = False
        for i in range(len(counts)):
            if counts[i] > 1 and sum(counts) > total:
                counts[i] -= 1
                changed = True
        if not changed:
            break

    remaining = total - sum(counts)
    while remaining > 0:
        changed = False
        for i in range(len(counts) - 1, -1, -1):
            if counts[i] < capacities[i]:
                counts[i] += 1
                remaining -= 1
                changed = True
                if remaining <= 0:
                    break
        if not changed:
            # Defensive fallback: add another outer row rather than overlap.
            rows += 1
            rr = inner_r + step * (rows - 1)
            cap = _max_arc_seats(rr, pitch)
            capacities.append(cap)
            take = min(cap, remaining)
            counts.append(take)
            remaining -= take

    outer_r = inner_r + step * (len(counts) - 1)
    diagram_h = int(outer_r + seat_r + 29 * s)
    base_y = int(diagram_h - 19 * s)
    return counts, inner_r, step, seat_r, diagram_h, base_y


def _fit_contain(src: Image.Image, max_size: tuple[int, int], bg: str) -> Image.Image:
    img = src.copy()
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    out = Image.new('RGB', max_size, bg)
    x = (max_size[0] - img.width) // 2
    y = (max_size[1] - img.height) // 2
    out.paste(img.convert('RGB'), (x, y))
    return out


def _parliament_block(w: int, s: float, data: dict, root: Path, theme: Theme) -> Image.Image | None:
    parties, total = _parse_parliament_parties(data.get('parties'), _parse_int_value(data.get('total_seats')))
    if not parties or total <= 0:
        return None

    assigned = sum(int(p['seats']) for p in parties)
    custom_majority = _parse_int_value(data.get('majority'))
    majority = custom_majority if custom_majority and 1 < custom_majority <= total else (total // 2 + 1)
    term = str(data.get('term') or '').strip()
    note = str(data.get('note') or '').strip()

    # В легенде показываем нераспределённые места, а в самом зале они уже серые.
    display_parties = list(parties)
    if assigned < total:
        display_parties.append({'name': 'Прочие / вакантные', 'seats': total - assigned, 'color': '#C8CCD1', '_remainder': True})

    title_font = _font(theme, max(10, int(12 * s)), bold=True)
    meta_font = _font(theme, max(9, int(11 * s)))
    legend_font = _font(theme, max(9, int(11 * s)))
    legend_font_small = _font(theme, max(8, int(10 * s)))
    tmp = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    pad_x = int(10 * s)
    pad_y = int(5 * s)
    gap = int(4 * s)

    term_lines = _wrap(tmp, term, title_font, w - pad_x * 2) if term else []
    meta_text = f'{total} мест / большинство {majority}'
    meta_lines = _wrap(tmp, meta_text, meta_font, w - pad_x * 2)
    note_lines = _wrap(tmp, note, legend_font_small, w - pad_x * 2) if note else []
    tlh = _line_h(tmp, title_font)
    mlh = _line_h(tmp, meta_font)
    llh = _line_h(tmp, legend_font)
    slh = _line_h(tmp, legend_font_small)

    _, _flag_item, logo_items = parliament_image_assets(data)
    logo_map: dict[str, Path] = {}
    for path, party_name in logo_items:
        media_path = _media_path(path, root)
        if media_path and party_name:
            logo_map[_norm_key(party_name)] = media_path
    any_logos = bool(logo_map)

    row_h = max(int(18 * s), llh)
    legend_h = len(display_parties) * row_h
    counts, inner_r, step, seat_r, diagram_h, base_y_offset = _hemicycle_layout(total, s)
    total_h = pad_y * 2 + diagram_h + len(meta_lines) * mlh + gap + legend_h
    if term_lines:
        total_h += len(term_lines) * tlh + gap
    if note_lines:
        total_h += gap + len(note_lines) * slh

    img = Image.new('RGB', (w, total_h), theme.panel)
    draw = ImageDraw.Draw(img)
    y = pad_y
    if term_lines:
        _draw_lines(draw, term_lines, (pad_x, y), title_font, theme.text, tlh, w - pad_x * 2, 'center')
        y += len(term_lines) * tlh + gap

    cx = w / 2
    base_y = y + base_y_offset
    seat_shape = _seat_shape(data.get('seat_shape'))
    colors: list[str] = []
    for party in parties:
        colors.extend([party['color']] * int(party['seats']))
    if len(colors) < total:
        colors.extend(['#C8CCD1'] * (total - len(colors)))
    colors = colors[:total]
    seat_i = 0
    for row_i, count in enumerate(counts):
        rr = inner_r + step * row_i
        angles = [math.pi / 2] if count == 1 else [math.pi - (j + 0.5) * math.pi / count for j in range(count)]
        for ang in angles:
            x = cx + rr * math.cos(ang)
            yy = base_y - rr * math.sin(ang)
            fill = colors[seat_i] if seat_i < len(colors) else '#C8CCD1'
            seat_i += 1
            box = (x - seat_r, yy - seat_r, x + seat_r, yy + seat_r)
            if seat_shape == 'square':
                draw.rectangle(box, fill=fill, outline='#202122', width=max(1, int(1.05 * s)))
            else:
                draw.ellipse(box, fill=fill, outline='#202122', width=max(1, int(1.05 * s)))
    y += diagram_h
    _draw_lines(draw, meta_lines, (pad_x, y), meta_font, theme.text, mlh, w - pad_x * 2, 'center')
    y += len(meta_lines) * mlh + gap

    sw = int(11 * s)
    logo_size = int(17 * s)
    icon_gap = int(5 * s)
    right_pad = pad_x
    logo_col = logo_size + icon_gap if any_logos else 0
    name_x = pad_x + sw + icon_gap + logo_col
    seats_max = 0
    for party in display_parties:
        seats = int(party['seats'])
        txt = f'{seats} / {seats / total * 100:.1f}%'
        seats_max = max(seats_max, _size(draw, txt, legend_font_small)[0])
    name_w = max(10, w - name_x - seats_max - right_pad - int(6 * s))

    for party in display_parties:
        row_top = y
        cy = row_top + row_h // 2
        draw.rectangle(
            (pad_x, cy - sw // 2, pad_x + sw, cy + sw // 2),
            fill=party['color'], outline=theme.border, width=max(1, int(0.8 * s))
        )
        if any_logos:
            logo_path = None if party.get('_remainder') else logo_map.get(_norm_key(party['name']))
            if logo_path and logo_path.is_file():
                try:
                    src = ImageOps.exif_transpose(Image.open(logo_path))
                    src.load()
                    logo = _fit_contain(src.convert('RGB'), (logo_size, logo_size), theme.panel)
                    img.paste(logo, (pad_x + sw + icon_gap, cy - logo_size // 2))
                except Exception:
                    pass
        name_lines = _wrap(draw, party['name'], legend_font, name_w)[:1]
        name_y = row_top + max(0, (row_h - llh) // 2) + max(1, int(1.2 * s))
        _draw_lines(draw, name_lines, (name_x, name_y), legend_font, theme.text, llh)
        seats_text = f'{int(party["seats"])} / {int(party["seats"]) / total * 100:.1f}%'
        seats_w = _size(draw, seats_text, legend_font_small)[0]
        seats_y = row_top + max(0, (row_h - slh) // 2) + max(1, int(1.2 * s))
        _draw_lines(
            draw, [seats_text],
            (w - right_pad - seats_w, seats_y),
            legend_font_small, theme.text_secondary, slh
        )
        y += row_h

    if note_lines:
        y += gap
        _draw_lines(draw, note_lines, (pad_x, y), legend_font_small, theme.text_secondary, slh, w - pad_x * 2, 'center')

    return img


def _parliament_corner_flag(data: dict, root: Path, s: float, theme: Theme) -> Image.Image | None:
    _, flag_item, _ = parliament_image_assets(data)
    if not flag_item:
        return None
    path = _media_path(flag_item[0], root)
    if not path:
        return None
    try:
        src = ImageOps.exif_transpose(Image.open(path))
        src.load()
        src = src.convert('RGB')
        max_w, max_h = int(76 * s), int(48 * s)
        src.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        border = max(1, int(1 * s))
        out = Image.new('RGB', (src.width + border * 2, src.height + border * 2), theme.panel)
        out.paste(src, (border, border))
        d = ImageDraw.Draw(out)
        d.rectangle((0, 0, out.width - 1, out.height - 1), outline=theme.border, width=border)
        return out
    except Exception:
        return None




VISUAL_TYPES = frozenset({'parliament'})


def _render_visual_page(page: Page, root: Path, path: Path, quality: str, watermark: bool) -> Path:
    global _ACTIVE_FONT_REG, _ACTIVE_FONT_BOLD
    theme=get_theme(page.theme); tpl=get_template(page.type); d=page.data or {}
    s=PILLOW_SCALE.get(quality,PILLOW_SCALE['high']); card_w=int(430*s); bw=max(1,int(theme.border_width*s)); inner_w=card_w-bw*2
    # selected font support
    _fk=d.get('_font_key') or 'default'; _uid=d.get('_font_user_id'); _reg=_bold=None
    if _fk and _fk!='default':
        if str(_fk).startswith('user:') and _uid is not None:
            _reg=resolve_user_font(root,int(_uid),str(_fk)); _bold=_reg
        else:
            _reg,_bold=resolve_font_files(str(_fk))
    _ACTIVE_FONT_REG=str(_reg) if _reg and _reg.is_file() else None
    _ACTIVE_FONT_BOLD=str(_bold or _reg) if _reg and _reg.is_file() else None
    corner_flag = _parliament_corner_flag(d, root, s, theme)
    reserve = (corner_flag.width + int(10*s)) if corner_flag is not None else 0
    min_header = (corner_flag.height + int(16*s)) if corner_flag is not None else 0
    blocks=[_header(inner_w,s,tpl,page,theme,right_reserve=reserve,min_height=min_header)]
    block=_parliament_block(inner_w,s,d,root,theme)
    if block is not None: blocks.append(block)
    if watermark: blocks.append(_footer(inner_w,s,theme))
    outer=int(12*s); content_h=sum(b.height for b in blocks)
    img=Image.new('RGB',(card_w+outer*2,content_h+outer*2+bw*2),theme.background); draw=ImageDraw.Draw(img)
    x=outer; y=outer; draw.rectangle((x,y,x+card_w-1,y+content_h+bw*2-1),fill=theme.panel,outline=theme.border,width=bw); x+=bw; y+=bw
    first_block_y = y
    for b in blocks:
        img.paste(b,(x,y)); y+=b.height
    if corner_flag is not None:
        fx = x + inner_w - corner_flag.width - int(8*s)
        fy = first_block_y + int(8*s)
        img.paste(corner_flag, (fx, fy))
    img.save(path,'PNG',compress_level=6,dpi=(144,144)); return path


def _footer(w: int, s: float, theme: Theme) -> Image.Image:
    font = _font(theme, max(7, int(9 * s)), bold=False)
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    pad = int(5 * s)
    lh = _line_h(tmp, font)
    img = Image.new("RGB", (w, pad * 2 + lh), theme.panel)
    _draw_lines(ImageDraw.Draw(img), ["INFOBOX BOT"], (pad, pad), font, theme.text_secondary, lh, w - pad * 2, "right")
    return img


def _standard_groups(tpl: Template, data: dict):
    skip = {"card_type_label", "title", "description", "image_caption", "anthem_duration", "parliament_chart_title", "parliament_parties", "parliament_majority", "parliament_note"}
    if tpl.subtitle_key:
        skip.add(tpl.subtitle_key)
    names = []
    for f in tpl.fields:
        if f.key not in skip and f.section not in names:
            names.append(f.section)
    for name in names:
        fields = [
            f for f in tpl.fields if f.section == name and f.key not in skip and data.get(f.key) not in (None, "", [])
        ]
        if fields:
            yield name, fields


def _render_news_tfr(
    page: Page,
    work_dir: Path,
    output: Path,
) -> Path:
    """News card in THE FIRE RISES browser-frame style."""
    here = Path(__file__).resolve().parent
    frame_path = here / "tfr_frame.png"
    if not frame_path.exists():
        raise FileNotFoundError("не нашёл tfr_frame.png рядом с ботом")

    frame = Image.open(frame_path).convert("RGBA")
    fw, fh = frame.size

    # coordinates measured on the 1536x2048 template
    IMG_BOX = (362, 599, 1159, 898)  # x0,y0,x1,y1 transparent hole
    BTN_BOX = (425, 1602, 1118, 1685)
    TITLE_AREA = (420, 580)  # y range for title between chrome and image
    BODY_TOP = 930
    BODY_BOTTOM = 1560
    CONTENT_X0 = 280
    CONTENT_X1 = 1256

    d = page.data
    title = str(d.get("title") or page.title or "Без названия").strip()
    body = str(d.get("body") or d.get("description") or "").strip()
    button = str(d.get("button_text") or "").strip()

    # base on black so transparent hole shows black until we paste image
    canvas = Image.new("RGBA", (fw, fh), (0, 0, 0, 255))

    # paste user image into the hole
    images = page_images(d)
    if images:
        media = _media_path(images[0], work_dir)
        if media is None:
            # allow absolute existing path (e.g. during tests / external media)
            cand = Path(str(images[0]))
            if cand.is_file():
                media = cand
        if media is not None:
            try:
                src = ImageOps.exif_transpose(Image.open(media))
                src.load()
                src = src.convert("RGB")
                box_w = IMG_BOX[2] - IMG_BOX[0]
                box_h = IMG_BOX[3] - IMG_BOX[1]
                fitted = ImageOps.fit(src, (box_w, box_h), Image.Resampling.LANCZOS)
                canvas.paste(fitted, (IMG_BOX[0], IMG_BOX[1]))
            except Exception:
                pass

    # overlay the frame (image shows through the hole)
    canvas = Image.alpha_composite(canvas, frame)
    draw = ImageDraw.Draw(canvas)

    def load_font(name: str, size: int):
        p = here / name
        try:
            return ImageFont.truetype(str(p), size)
        except Exception:
            return ImageFont.load_default()

    title_font = load_font("ETORO-VF-V0.8.TTF", 54)
    # fallback if variable font fails at size
    try:
        title_font.getbbox("A")
    except Exception:
        title_font = load_font("PixeloidSans-Bold.otf", 42)

    body_font = load_font("PixeloidSans.otf", 28)
    btn_font = load_font("PixeloidSans.otf", 26)

    # title centered between chrome and image
    max_title_w = CONTENT_X1 - CONTENT_X0
    words = title.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        try:
            tw = draw.textlength(test, font=title_font)
        except Exception:
            tw = len(test) * 28
        if tw <= max_title_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    lines = lines[:3] or ["Без названия"]
    try:
        line_h = title_font.getbbox("Ag")[3] - title_font.getbbox("Ag")[1] + 8
    except Exception:
        line_h = 58
    total_h = line_h * len(lines)
    ty = TITLE_AREA[0] + max(0, (TITLE_AREA[1] - TITLE_AREA[0] - total_h) // 2)
    for line in lines:
        try:
            tw = draw.textlength(line, font=title_font)
        except Exception:
            tw = len(line) * 28
        tx = (fw - int(tw)) // 2
        draw.text((tx, ty), line, font=title_font, fill=(20, 20, 20, 255))
        ty += line_h

    # body text
    if body:
        max_body_w = CONTENT_X1 - CONTENT_X0
        body_lines: list[str] = []
        for para in body.splitlines() or [body]:
            para = para.strip()
            if not para:
                body_lines.append("")
                continue
            words = para.split()
            cur = ""
            for w in words:
                test = (cur + " " + w).strip()
                try:
                    tw = draw.textlength(test, font=body_font)
                except Exception:
                    tw = len(test) * 14
                if tw <= max_body_w or not cur:
                    cur = test
                else:
                    body_lines.append(cur)
                    cur = w
            if cur:
                body_lines.append(cur)
        try:
            blh = body_font.getbbox("Ag")[3] - body_font.getbbox("Ag")[1] + 10
        except Exception:
            blh = 34
        max_rows = max(1, (BODY_BOTTOM - BODY_TOP) // blh)
        body_lines = body_lines[:max_rows]
        by = BODY_TOP
        for line in body_lines:
            draw.text((CONTENT_X0, by), line, font=body_font, fill=(25, 25, 25, 255))
            by += blh

    # button text centered on the button
    if button:
        bx0, by0, bx1, by1 = BTN_BOX
        try:
            tw = draw.textlength(button, font=btn_font)
            th = btn_font.getbbox("Ag")[3] - btn_font.getbbox("Ag")[1]
        except Exception:
            tw, th = len(button) * 12, 24
        btx = bx0 + (bx1 - bx0 - int(tw)) // 2
        bty = by0 + (by1 - by0 - int(th)) // 2 - 2
        # slight glow / shadow
        draw.text((btx + 1, bty + 1), button, font=btn_font, fill=(0, 0, 0, 180))
        draw.text((btx, bty), button, font=btn_font, fill=(210, 230, 200, 255))

    out = canvas.convert("RGB")
    out.save(output, "PNG", compress_level=6)
    return output


def _render_superevent_tfr(
    page: Page,
    work_dir: Path,
    output: Path,
) -> Path:
    """Superevent card in THE FIRE RISES style: frame + additive pink-blue gradient."""
    here = Path(__file__).resolve().parent
    frame_path = here / "tfr_se_frame.png"
    grad_path = here / "tfr_se_grad.png"
    btn_path = here / "tfr_se_btn.png"
    if not frame_path.exists() or not grad_path.exists():
        raise FileNotFoundError("не нашёл tfr_se_frame.png / tfr_se_grad.png рядом с ботом")

    frame = Image.open(frame_path).convert("RGBA")
    grad = Image.open(grad_path).convert("RGBA")
    btn_panel = Image.open(btn_path).convert("RGBA") if btn_path.exists() else None
    fw, fh = frame.size
    if grad.size != (fw, fh):
        grad = grad.resize((fw, fh), Image.Resampling.LANCZOS)
    if btn_panel is not None and btn_panel.size != (fw, fh):
        btn_panel = btn_panel.resize((fw, fh), Image.Resampling.LANCZOS)

    # text regions measured on 2048x1536 template
    TITLE_Y0, TITLE_Y1 = 155, 230
    # панель кнопки/текста (отдельный слой tfr_se_btn.png)
    BODY_BOX = (450, 1010, 1600, 1240)
    BTN_BOX = (780, 1295, 1268, 1355)
    # main image area inside the frame
    # на всю внутреннюю область рамки, чтобы градиент лег на всё фото
    IMG_BOX = (50, 248, 1998, 1265)

    d = page.data
    title = str(d.get("title") or page.title or "Без названия").strip()
    body = str(d.get("body") or d.get("description") or "").strip()
    button = str(d.get("button_text") or "").strip()

    canvas = Image.new("RGBA", (fw, fh), (0, 0, 0, 255))

    # user image under the gradient
    images = page_images(d)
    if images:
        media = _media_path(images[0], work_dir)
        if media is None:
            cand = Path(str(images[0]))
            if cand.is_file():
                media = cand
        if media is not None:
            try:
                src = ImageOps.exif_transpose(Image.open(media))
                src.load()
                src = src.convert("RGB")
                box_w = IMG_BOX[2] - IMG_BOX[0]
                box_h = IMG_BOX[3] - IMG_BOX[1]
                fitted = ImageOps.fit(src, (box_w, box_h), Image.Resampling.LANCZOS)
                canvas.paste(fitted, (IMG_BOX[0], IMG_BOX[1]))
            except Exception:
                pass

    # additive blend of pink-blue gradient over everything so far
    # result = min(255, base + grad * alpha)  — без numpy
    from PIL import ImageChops

    base = canvas.convert("RGB")
    g_rgb = grad.convert("RGB")
    g_a = grad.split()[-1]
    premul = Image.new("RGB", base.size, (0, 0, 0))
    premul.paste(g_rgb, mask=g_a)  # = grad * alpha
    added = ImageChops.add(base, premul)  # clip 0..255
    canvas = added.convert("RGBA")

    # metal frame on top
    canvas = Image.alpha_composite(canvas, frame)
    # отдельная кнопка/панель поверх рамки
    if btn_panel is not None:
        canvas = Image.alpha_composite(canvas, btn_panel)
    draw = ImageDraw.Draw(canvas)

    def load_font(name: str, size: int):
        p = here / name
        try:
            return ImageFont.truetype(str(p), size)
        except Exception:
            return ImageFont.load_default()

    title_font = load_font("PixeloidSans.otf", 36)
    body_font = load_font("PixeloidSans.otf", 28)
    btn_font = load_font("PixeloidSans.otf", 26)

    def wrap(text: str, font, max_w: int) -> list[str]:
        lines: list[str] = []
        for para in (text.splitlines() or [text]):
            para = para.strip()
            if not para:
                lines.append("")
                continue
            words = para.split()
            cur = ""
            for w in words:
                test = (cur + " " + w).strip()
                try:
                    tw = draw.textlength(test, font=font)
                except Exception:
                    tw = len(test) * 14
                if tw <= max_w or not cur:
                    cur = test
                else:
                    lines.append(cur)
                    cur = w
            if cur:
                lines.append(cur)
        return lines or [""]

    # title centered in top bar (drawn AFTER gradient so it stays clean)
    max_tw = 1600
    t_lines = wrap(title, title_font, max_tw)[:2]
    try:
        lh = title_font.getbbox("Ag")[3] - title_font.getbbox("Ag")[1] + 6
    except Exception:
        lh = 40
    total_h = lh * len(t_lines)
    ty = TITLE_Y0 + max(0, (TITLE_Y1 - TITLE_Y0 - total_h) // 2)
    for line in t_lines:
        try:
            tw = int(draw.textlength(line, font=title_font))
        except Exception:
            tw = len(line) * 18
        tx = (fw - tw) // 2
        draw.text((tx, ty), line, font=title_font, fill=(230, 230, 235, 255))
        ty += lh

    # body text in the lower panel
    if body:
        bx0, by0, bx1, by1 = BODY_BOX
        max_bw = bx1 - bx0
        b_lines = wrap(body, body_font, max_bw)
        try:
            blh = body_font.getbbox("Ag")[3] - body_font.getbbox("Ag")[1] + 8
        except Exception:
            blh = 34
        max_rows = max(1, (by1 - by0) // blh)
        b_lines = b_lines[:max_rows]
        total_h = blh * len(b_lines)
        by = by0 + max(0, (by1 - by0 - total_h) // 2)
        for line in b_lines:
            try:
                tw = int(draw.textlength(line, font=body_font))
            except Exception:
                tw = len(line) * 14
            tx = bx0 + (max_bw - tw) // 2
            draw.text((tx, by), line, font=body_font, fill=(245, 245, 250, 255))
            by += blh

    # button label
    if button:
        bx0, by0, bx1, by1 = BTN_BOX
        try:
            tw = int(draw.textlength(button, font=btn_font))
            th = btn_font.getbbox("Ag")[3] - btn_font.getbbox("Ag")[1]
        except Exception:
            tw, th = len(button) * 12, 24
        btx = bx0 + (bx1 - bx0 - tw) // 2
        bty = by0 + (by1 - by0 - th) // 2 - 2
        draw.text((btx + 1, bty + 1), button, font=btn_font, fill=(0, 0, 0, 160))
        draw.text((btx, bty), button, font=btn_font, fill=(235, 235, 240, 255))

    out = canvas.convert("RGB")
    out.save(output, "PNG", compress_level=6)
    return output



def _render_mirotorets(page: Page, root: Path, path: Path, quality: str = "high") -> Path:
    """Карточка в стиле сайта Миротворец (Pillow, без водяных знаков)."""
    d = page.data or {}
    s = PILLOW_SCALE.get(quality, PILLOW_SCALE["high"])
    W = int(780 * s)
    pad = int(16 * s)
    blue = (26, 95, 180)
    border = (184, 192, 204)
    text_c = (0, 0, 0)
    red = (196, 30, 58)
    gray = (102, 102, 102)
    bg = (255, 255, 255)
    light = (247, 248, 250)

    def font(sz, bold=False):
        here = Path(__file__).resolve().parent
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        for cand in (here / name, Path("/usr/share/fonts/truetype/dejavu") / name):
            if cand.is_file():
                return ImageFont.truetype(str(cand), int(sz * s))
        return ImageFont.load_default()

    f_body = font(16.5)
    f_lab = font(16.5, bold=True)
    f_nd = font(22, bold=True)
    f_foot = font(14.5)
    f_top = font(17)

    birth = str(d.get("birth_date") or "").strip()
    country = str(d.get("country") or "Россия").strip()
    rank = str(d.get("rank") or "").strip()
    unit = str(d.get("unit") or "").strip()
    position = str(d.get("position") or "").strip()
    personal = str(d.get("personal_number") or "").strip()
    passport = str(d.get("passport") or "").strip()
    birth_place = str(d.get("birth_place") or "").strip()
    source = str(d.get("source") or "").strip()
    name_title = str(d.get("title") or page.title or "").strip()
    desc = str(
        d.get("description")
        or (
            "Российский военный преступник.\n"
            "Участник нападения фашистской россии на Украину 24.02.2022.\n"
            "В/служащий вооруженных сил российской федерации."
        )
    ).strip()
    hashtags = str(d.get("hashtags") or "#StopRussianAggression").strip()
    footer_text = str(
        d.get("footer")
        or (
            "Центр «Миротворец» просит правоохранительные органы рассматривать данную "
            "публикацию на сайте как заявление о совершении этим гражданином осознанных деяний "
            "против национальной безопасности Украины, мира, безопасности человечества и "
            "международного правопорядка, а также иных правонарушений."
        )
    ).strip()

    # фото: фиксированный квадрат, картинка вписана целиком, рамка ровно по боксу
    photo_side = int(112 * s)
    bw = max(1, int(1 * s))
    photo_img = None
    imgs = page_images(d)
    if imgs:
        raw = Path(imgs[0])
        mp = raw if raw.is_absolute() else (root / raw)
        if mp.is_file():
            try:
                src = Image.open(mp).convert("RGB")
                # cover: заполняет бокс без полей внутри рамки
                photo_img = ImageOps.fit(
                    src,
                    (photo_side, photo_side),
                    method=Image.Resampling.LANCZOS,
                )
            except Exception:
                photo_img = None

    def wrap(text: str, fnt, max_w: int) -> list[str]:
        words = str(text).split()
        if not words:
            return [""]
        lines, cur = [], words[0]
        for w in words[1:]:
            trial = cur + " " + w
            if fnt.getlength(trial) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        return lines

    body_lines: list[tuple[str, object, tuple]] = []
    for line in desc.split("\n"):
        line = line.strip()
        if line:
            body_lines.append((line, f_body, (0, 0, 0)))
    field_rows = []
    if unit:
        field_rows.append(("Подразделение:", unit))
    if position:
        field_rows.append(("Должность:", position))
    if rank:
        field_rows.append(("Звание:", rank))
    if personal:
        field_rows.append(("Личный номер:", personal))
    if birth:
        field_rows.append(("Дата рождения:", birth))
    if passport:
        field_rows.append(("Паспорт:", passport))
    if birth_place:
        field_rows.append(("Место рождения:", birth_place))
    if source:
        field_rows.append(("Источник:", source))
    else:
        field_rows.append(("", "Источник"))
    for lab, val in field_rows:
        if lab:
            body_lines.append((f"{lab} {val}", f_body, (0, 0, 0)))
        else:
            body_lines.append((val, f_body, (0, 0, 0)))
    for tg in hashtags.split():
        if tg.startswith("#"):
            body_lines.append((tg, f_body, (0, 0, 0)))

    body_w = W - 2 * pad
    line_h = int(24 * s)
    body_h = 0
    wrapped: list[tuple[list[str], object, tuple]] = []
    for text, fnt, col in body_lines:
        ls = wrap(text, fnt, body_w)
        wrapped.append((ls, fnt, col))
        body_h += len(ls) * line_h
    foot_ls = wrap(footer_text, f_foot, body_w)
    body_h += int(14 * s) + len(foot_ls) * int(21 * s)

    header_h = int(36 * s)
    # верхний блок: фото + мета; высота = фото + поля сверху/снизу
    top_pad = int(12 * s)
    top_h = photo_side + top_pad * 2
    total_h = header_h + top_h + pad + body_h + pad

    im = Image.new("RGB", (W, total_h), bg)
    dr = ImageDraw.Draw(im)

    # синяя шапка + имя слева
    dr.rectangle([0, 0, W, header_h], fill=blue)
    if name_title:
        f_name = font(15, bold=True)
        dr.text((int(14 * s), header_h // 2 - int(10 * s)), name_title, fill=(255, 255, 255), font=f_name)
    # внешняя рамка карточки
    dr.rectangle([0, 0, W - 1, total_h - 1], outline=border, width=max(1, int(s)))

    # фото слева, рамка ровно по краю картинки
    bx0 = int(12 * s)
    by0 = header_h + top_pad
    bx1 = bx0 + photo_side
    by1 = by0 + photo_side
    if photo_img is not None:
        im.paste(photo_img, (bx0, by0))
        dr.rectangle([bx0, by0, bx1 - 1, by1 - 1], outline=border, width=bw)
    else:
        dr.rectangle([bx0, by0, bx1 - 1, by1 - 1], outline=border, width=bw, fill=light)
        nd = "N/D"
        tw = f_nd.getlength(nd)
        dr.text(
            (bx0 + (photo_side - tw) / 2, by0 + (photo_side - int(28 * s)) / 2),
            nd,
            fill=gray,
            font=f_nd,
        )

    # вертикальный разделитель
    div_x = bx1 + int(10 * s)
    dr.line([div_x, header_h, div_x, header_h + top_h], fill=border, width=max(1, int(s)))

    # мета справа: дата, страна, пунктир ТОЛЬКО под строкой "Страна"
    mx = div_x + int(14 * s)
    my = header_h + int(18 * s)
    row_h = int(26 * s)
    if birth:
        line = f"Дата рождения: {birth}"
        dr.text((mx, my), line, fill=(0, 0, 0), font=f_top)
        my += row_h
    country_line = ""
    if country:
        country_line = f"Страна: {country}"
        dr.text((mx, my), country_line, fill=(0, 0, 0), font=f_top)
        # пунктир под строкой "Страна", на всю ширину правой колонки
        dash_y = my + int(22 * s)
        dash_end = W - pad
        x = mx
        dash_len = int(6 * s)
        gap = int(5 * s)
        while x < dash_end:
            x2 = min(x + dash_len, dash_end)
            dr.line([x, dash_y, x2, dash_y], fill=(154, 163, 176), width=max(1, int(s)))
            x += dash_len + gap

    # линия под верхним блоком
    dr.line([0, header_h + top_h, W, header_h + top_h], fill=border, width=max(1, int(s)))

    # тело
    y = header_h + top_h + pad
    for ls, fnt, col in wrapped:
        for line in ls:
            dr.text((pad, y), line, fill=col, font=fnt)
            y += line_h
    y += int(10 * s)
    for line in foot_ls:
        dr.text((pad, y), line, fill=red, font=f_foot)
        y += int(21 * s)

    path = Path(path)
    im.save(path, format="PNG", optimize=True)
    return path




def _primary_font(font):
    """Pillow text APIs need a real font, not (primary, fallback) tuple."""
    if isinstance(font, tuple):
        return font[0]
    return font


def _anthem_block(w: int, s: float, title: str, duration: str, theme: Theme) -> Image.Image:
    """Wikipedia TimedMediaHandler-style audio bar: grey track, white ▶, black time badge."""
    pad = int(8 * s)
    f_title = _font(theme, max(9, int(12 * s)), bold=False)
    f_time = _primary_font(_font(theme, max(8, int(10 * s)), bold=False))
    tmp = Image.new("RGB", (10, 10), theme.panel)
    dr = ImageDraw.Draw(tmp)
    title_lines = _wrap(dr, title, f_title, w - pad * 2)
    th = _line_h(dr, f_title)
    # Wikipedia mobile: compact grey bar ~36–40px
    bar_h = int(28 * s)
    h = pad // 2 + len(title_lines) * th + int(8 * s) + bar_h + pad // 2
    im = Image.new("RGB", (w, h), theme.panel)
    dr = ImageDraw.Draw(im)
    y = pad // 2
    link_col = theme.link if hasattr(theme, "link") else theme.accent
    _draw_lines(dr, title_lines, (pad, y), f_title, link_col, th, w - pad * 2, "center")
    y += len(title_lines) * th + int(8 * s)

    # Player bar — solid medium grey like Wikipedia (#7c7c7c)
    bx0, by0 = pad, y
    bx1, by1 = w - pad, y + bar_h
    bar_fill = "#7c7c7c"
    radius = max(2, int(3 * s))
    dr.rounded_rectangle([bx0, by0, bx1, by1], radius=radius, fill=bar_fill)

    cy = (by0 + by1) // 2

    # White play triangle (▶) — not a filled circle
    tri_cx = bx0 + int(15 * s)
    tri_size = int(7 * s)
    # triangle pointing right
    tri = [
        (tri_cx - tri_size // 2, cy - tri_size),
        (tri_cx - tri_size // 2, cy + tri_size),
        (tri_cx + tri_size, cy),
    ]
    dr.polygon(tri, fill="#ffffff")

    # Time badge — black rounded pill, white text (right side)
    dur = (duration or "0:00").strip() or "0:00"
    try:
        tw = int(f_time.getlength(dur))
    except Exception:
        box = dr.textbbox((0, 0), dur, font=f_time)
        tw = box[2] - box[0]
    badge_pad_x = int(6 * s)
    badge_pad_y = int(3 * s)
    badge_h = int(18 * s)
    badge_w = tw + badge_pad_x * 2
    badge_x1 = bx1 - int(6 * s)
    badge_x0 = badge_x1 - badge_w
    badge_y0 = cy - badge_h // 2
    badge_y1 = badge_y0 + badge_h
    dr.rounded_rectangle(
        [badge_x0, badge_y0, badge_x1, badge_y1],
        radius=max(2, int(4 * s)),
        fill="#000000",
    )
    # vertically center text in badge
    try:
        tb = dr.textbbox((0, 0), dur, font=f_time)
        th_t = tb[3] - tb[1]
        ty = badge_y0 + (badge_h - th_t) // 2 - tb[1]
    except Exception:
        ty = cy - int(7 * s)
    dr.text((badge_x0 + badge_pad_x, ty), dur, fill="#ffffff", font=f_time)
    return im

def render_pillow(
    page: Page,
    work_dir: str | Path,
    quality: str,
    output: str | Path,
    watermark: bool = True,
) -> Path:
    if page.theme == "olddoc":
        from olddoc import render_olddoc

        return render_olddoc(page, work_dir, quality, output, watermark)

    root = Path(work_dir).resolve()
    path = Path(output).resolve()

    if page.type == "mirotorets" or page.theme == "mirotorets":
        return _render_mirotorets(page, root, path, quality)
    if page.type in VISUAL_TYPES:
        return _render_visual_page(page, root, path, quality, watermark)
    if page.type == "news":
        return _render_news_tfr(page, root, path)
    if page.type == "superevent":
        return _render_superevent_tfr(page, root, path)

    global _ACTIVE_FONT_REG, _ACTIVE_FONT_BOLD
    theme = get_theme(page.theme)
    tpl = get_template(page.type)
    # пользовательский/выбранный шрифт
    _fk = (page.data or {}).get("_font_key") or "default"
    _uid = (page.data or {}).get("_font_user_id")
    _reg = _bold = None
    if _fk and _fk != "default":
        if str(_fk).startswith("user:") and _uid is not None:
            _reg = resolve_user_font(root, int(_uid), str(_fk))
            _bold = _reg
        else:
            _reg, _bold = resolve_font_files(str(_fk))
    if _reg and _reg.is_file():
        page.data["_pillow_font_reg"] = str(_reg)
        page.data["_pillow_font_bold"] = str(_bold or _reg)
        _ACTIVE_FONT_REG = str(_reg)
        _ACTIVE_FONT_BOLD = str(_bold or _reg)
    else:
        _ACTIVE_FONT_REG = _ACTIVE_FONT_BOLD = None
    d = page.data
    s = PILLOW_SCALE.get(quality, PILLOW_SCALE["high"])
    card_w = int(360 * s)
    bw = max(1, int(theme.border_width * s))
    inner_w = card_w - bw * 2
    blocks = [_header(inner_w, s, tpl, page, theme)]

    row_index = 0
    if tpl.key == "battle":
        blocks.extend(_battle_blocks(page, root, inner_w, s, theme))
    else:
        media = []
        for i, value in enumerate(page_images(d)):
            media_path = _media_path(value, root)
            if media_path:
                media.append((media_path, image_caption(d, value, i)))
        if media:
            pic = _gallery(inner_w, s, media, theme)
            if pic:
                blocks.append(pic)

        # гимн (полоска как в вики)
        anthem = str(d.get("anthem") or "").strip()
        if anthem:
            blocks.append(_anthem_block(inner_w, s, anthem, str(d.get("anthem_duration") or "").strip(), theme))

        # карты территорий
        maps = []
        for i, value in enumerate(map_images(d)):
            media_path = _media_path(value, root)
            if media_path:
                maps.append((media_path, map_image_caption(d, value)))
        if maps:
            pic = _gallery(inner_w, s, maps, theme)
            if pic:
                blocks.append(pic)

        for title, fields in _standard_groups(tpl, d):
            blocks.append(_section_title(inner_w, s, title, theme))
            if any(f.column for f in fields):
                blocks.append(_side_rows(inner_w, s, fields, d, theme))
            else:
                for f in fields:
                    row_index += 1
                    blocks.append(_row(inner_w, s, f.label, d[f.key], theme, alternate=(row_index % 2 == 0)))


    custom = [
        x
        for x in d.get("custom_fields") or []
        if isinstance(x, dict) and x.get("value") not in (None, "")
    ]
    if custom:
        blocks.append(_section_title(inner_w, s, "Дополнительные сведения", theme))
        for x in custom:
            row_index += 1
            blocks.append(_row(inner_w, s, x.get("name", "Поле"), x.get("value", ""), theme, alternate=(row_index % 2 == 0)))

    for sec in d.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        rows = [
            x
            for x in sec.get("fields") or []
            if isinstance(x, dict) and x.get("value") not in (None, "")
        ]
        if not rows:
            continue
        blocks.append(_section_title(inner_w, s, str(sec.get("title") or "Раздел"), theme))
        for x in rows:
            row_index += 1
            blocks.append(_row(inner_w, s, x.get("name", "Поле"), x.get("value", ""), theme, alternate=(row_index % 2 == 0)))

    if d.get("description"):
        blocks.append(_section_title(inner_w, s, "Описание", theme))
        blocks.append(_description(inner_w, s, d["description"], theme))
    if watermark:
        blocks.append(_footer(inner_w, s, theme))

    outer = int(12 * s)
    content_h = sum(x.height for x in blocks)
    img = Image.new("RGB", (card_w + outer * 2, content_h + outer * 2 + bw * 2), theme.background)
    draw = ImageDraw.Draw(img)
    x = outer
    y = outer
    draw.rectangle((x, y, x + card_w - 1, y + content_h + bw * 2 - 1), fill=theme.panel, outline=theme.border, width=bw)
    x += bw
    y += bw
    for block in blocks:
        img.paste(block, (x, y))
        y += block.height

    img.save(path, "PNG", compress_level=6, dpi=(144, 144))
    return path
