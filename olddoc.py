"""Old document theme: aged paper, optional coffee stains, seed-based variations."""
from __future__ import annotations

import hashlib
import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from media import battle_image_groups, image_caption, map_image_caption, map_images, page_images
from models import Page
from templates import Field, Template, get_template
from themes import Theme, get_theme

HERE = Path(__file__).resolve().parent
# Textures live next to the bot sources (root folder), not in a subfolder.
PAPERS = [
    HERE / "paper1.png",
    HERE / "paper2.png",
    HERE / "paper3.png",
    HERE / "paper4.png",
    HERE / "paper5.png",
    HERE / "paper6.png",
]
STAINS = [HERE / "stain1.png", HERE / "stain2.png"]

SCALE = {"standard": 1.25, "high": 1.5, "ultra": 2.0}


STAIN_COUNT_MAX = 5
PAPER_COUNT = 6

def paper_count() -> int:
    return max(1, sum(1 for p in PAPERS if p.is_file()))



def ensure_old_meta(data: dict) -> dict:
    """Ensure old-document options exist; mutate and return data."""
    if "_old_seed" not in data:
        raw = f"{data.get('title', '')}|{random.randint(1, 10**9)}"
        data["_old_seed"] = int(hashlib.md5(raw.encode()).hexdigest()[:8], 16)
    if "_old_stains" not in data:
        data["_old_stains"] = True
    # 0..STAIN_COUNT_MAX cups; if stains off, treated as 0 at render
    if "_old_stain_count" not in data:
        data["_old_stain_count"] = 0
    data["_old_stain_count"] = max(0, min(STAIN_COUNT_MAX, int(data.get("_old_stain_count", 0) or 0)))
    data["_old_stains"] = data["_old_stain_count"] > 0
    # paper variant index 0..PAPER_COUNT-1
    if "_old_paper" not in data:
        data["_old_paper"] = 0
    data["_old_paper"] = int(data.get("_old_paper", 0) or 0) % PAPER_COUNT
    # drunk (jittery) text off by default
    if "_old_drunk" not in data:
        data["_old_drunk"] = False
    data["_old_drunk"] = bool(data.get("_old_drunk", False))
    # drunk (tilted) flags off by default
    if "_old_drunk_flags" not in data:
        data["_old_drunk_flags"] = False
    data["_old_drunk_flags"] = bool(data.get("_old_drunk_flags", False))
    # "под веществами" — extreme mess
    if "_old_substances" not in data:
        data["_old_substances"] = False
    data["_old_substances"] = bool(data.get("_old_substances", False))
    # inner darkened content window
    if "_old_window" not in data:
        data["_old_window"] = True
    data["_old_window"] = bool(data.get("_old_window", True))
    # outer paper outline stroke
    if "_old_outline" not in data:
        data["_old_outline"] = True
    data["_old_outline"] = bool(data.get("_old_outline", True))
    if "_old_bw" not in data:
        data["_old_bw"] = False
    data["_old_bw"] = bool(data.get("_old_bw", False))
    return data


def new_seed(data: dict) -> int:
    data["_old_seed"] = random.randint(1, 2**31 - 1)
    return data["_old_seed"]


def cycle_stain_count(data: dict) -> int:
    return cycle_stain_count_step(data, 1)


def cycle_paper(data: dict, step: int = 1) -> int:
    ensure_old_meta(data)
    n = max(1, paper_count())
    data["_old_paper"] = (int(data["_old_paper"]) + step) % n
    return data["_old_paper"]


def cycle_stain_count_step(data: dict, step: int = 1) -> int:
    ensure_old_meta(data)
    mod = STAIN_COUNT_MAX + 1
    data["_old_stain_count"] = (int(data["_old_stain_count"]) + step) % mod
    data["_old_stains"] = data["_old_stain_count"] > 0
    return data["_old_stain_count"]



def toggle_drunk(data: dict) -> bool:
    ensure_old_meta(data)
    data["_old_drunk"] = not bool(data["_old_drunk"])
    return data["_old_drunk"]


def toggle_drunk_flags(data: dict) -> bool:
    ensure_old_meta(data)
    data["_old_drunk_flags"] = not bool(data["_old_drunk_flags"])
    return data["_old_drunk_flags"]


def toggle_substances(data: dict) -> bool:
    ensure_old_meta(data)
    data["_old_substances"] = not bool(data["_old_substances"])
    return data["_old_substances"]


def toggle_window(data: dict) -> bool:
    ensure_old_meta(data)
    data["_old_window"] = not bool(data["_old_window"])
    return data["_old_window"]


def toggle_outline(data: dict) -> bool:
    ensure_old_meta(data)
    data["_old_outline"] = not bool(data["_old_outline"])
    return data["_old_outline"]


def toggle_bw(data: dict) -> bool:
    ensure_old_meta(data)
    data["_old_bw"] = not bool(data["_old_bw"])
    return data["_old_bw"]


def _paper_outline(mask: Image.Image, width: int = 3, color=(42, 32, 22, 220)) -> Image.Image:
    """Outer stroke along hard paper edge (follows torn mask)."""
    # edge = dilated mask minus original
    solid = mask.point(lambda v: 255 if v > 127 else 0)
    dil = solid
    for _ in range(max(1, width)):
        dil = dil.filter(ImageFilter.MaxFilter(3))
    edge = ImageChops.subtract(dil, solid)
    stroke = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    stroke.paste(color, (0, 0), edge)
    return stroke


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def _serif(size: int, bold: bool = False, italic: bool = False):
    if bold and italic:
        name = "LiberationSerif-Bold.ttf"  # no bold-italic bundled; fall back
    elif bold:
        name = "LiberationSerif-Bold.ttf"
    elif italic:
        name = "LiberationSerif-Italic.ttf"
    else:
        name = "LiberationSerif-Regular.ttf"
    paths = [
        HERE / name,
        Path("/usr/share/fonts/truetype/liberation") / name,
        HERE / "DejaVuSerif.ttf" if not bold else HERE / "DejaVuSerif-Bold.ttf",
        Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSerif-Bold.ttf" if bold else "DejaVuSerif.ttf"),
    ]
    for p in paths:
        if p and p.is_file():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    return ImageFont.load_default(size=size)


def _size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text or "Ag", font=font)
    return box[2] - box[0], box[3] - box[1]


def _wrap(draw: ImageDraw.ImageDraw, value: object, font, max_w: int) -> list[str]:
    text = "\n".join(str(x) for x in value) if isinstance(value, (list, tuple)) else str(value)
    out: list[str] = []
    for raw in text.split("\n"):
        words = raw.split()
        if not words:
            out.append("")
            continue
        line = ""
        for word in words:
            cand = word if not line else f"{line} {word}"
            if line and _size(draw, cand, font)[0] > max_w:
                out.append(line)
                line = word
            else:
                line = cand
        if line:
            out.append(line)
    return out or [""]


def _line_h(draw: ImageDraw.ImageDraw, font) -> int:
    return int(_size(draw, "Аg", font)[1] * 1.38)


def _paper_bg(w: int, h: int, rng: random.Random, paper_index: int = 0) -> Image.Image:
    papers = [p for p in PAPERS if p.is_file()]
    if not papers:
        return Image.new("RGB", (w, h), (236, 226, 205))

    idx = paper_index % len(papers)
    src = Image.open(papers[idx]).convert("RGB")
    sw, sh = src.size
    scale = max(w / sw, h / sh) * 1.04
    nw, nh = max(w + 2, int(sw * scale)), max(h + 2, int(sh * scale))
    src = src.resize((nw, nh), Image.Resampling.LANCZOS)
    ox = max(0, (nw - w) // 2 + rng.randint(-8, 8))
    oy = max(0, (nh - h) // 2 + rng.randint(-8, 8))
    ox = min(ox, max(0, nw - w))
    oy = min(oy, max(0, nh - h))
    img = src.crop((ox, oy, ox + w, oy + h))

    # subtle tone only — no heavy "filter pack"
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.98, 1.03))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.97, 1.05))
    img = ImageEnhance.Color(img).enhance(rng.uniform(0.95, 1.02))
    return img


def _soft_paper_mask(w: int, h: int, rng: random.Random, depth: int = 18) -> Image.Image:
    """Hard jagged torn edge — sharp, no soft soap."""
    return _torn_mask(w, h, rng, depth=depth)


def _torn_mask(w: int, h: int, rng: random.Random, depth: int = 18) -> Image.Image:
    """Hard irregular paper tear — crisp binary edge."""
    mask = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(mask)
    depth = max(12, min(depth, 32))

    def edge_points(length: int, axis: str, side: str) -> list[tuple[int, int]]:
        pts = []
        step = max(3, length // 95)
        n = max(16, length // step)
        for i in range(n + 1):
            t = i / n
            pos = int(t * (length - 1))
            # frequent sharp nicks + occasional deep rip
            if rng.random() < 0.18:
                off = int(depth * rng.uniform(0.7, 1.25))
            elif rng.random() < 0.35:
                off = int(depth * rng.uniform(0.4, 0.75))
            else:
                off = int(depth * rng.uniform(0.12, 0.4))
            off = max(3, min(depth + 8, off))
            # micro zig-zag
            if i > 0 and rng.random() < 0.4:
                pos = max(0, min(length - 1, pos + rng.randint(-step // 2, step // 2)))
            if axis == "x":
                y = off if side == "top" else h - 1 - off
                pts.append((pos, y))
            else:
                x = off if side == "left" else w - 1 - off
                pts.append((x, pos))
        return pts

    for axis, side, corner_a, corner_b in (
        ("x", "top", (0, 0), (w - 1, 0)),
        ("x", "bottom", (0, h - 1), (w - 1, h - 1)),
        ("y", "left", (0, 0), (0, h - 1)),
        ("y", "right", (w - 1, 0), (w - 1, h - 1)),
    ):
        pts = edge_points(w if axis == "x" else h, axis, side)
        draw.polygon([corner_a] + pts + [corner_b], fill=0)

    # NO blur — hard cut only
    return mask

def _apply_stains(img: Image.Image, rng: random.Random, count: int = 1) -> Image.Image:
    """Place `count` cup stains of a fixed size (position/rotation still vary by seed)."""
    stains = [p for p in STAINS if p.is_file()]
    if not stains or count <= 0:
        return img
    out = img.convert("RGBA")
    w, h = out.size
    # fixed relative size of the cup ring
    fixed_frac = 0.32
    for i in range(count):
        stain = Image.open(stains[i % len(stains)]).convert("RGBA")
        target = max(40, int(min(w, h) * fixed_frac))
        scale = target / max(stain.size)
        nw = max(20, int(stain.width * scale))
        nh = max(20, int(stain.height * scale))
        stain = stain.resize((nw, nh), Image.Resampling.LANCZOS)
        if rng.random() < 0.5:
            stain = stain.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if rng.random() < 0.5:
            stain = stain.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        angle = rng.uniform(-35, 35)
        # keep alpha hard on expand
        rgb = stain.convert("RGB")
        alpha = stain.split()[3]
        rgb_r = rgb.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0))
        a_r = alpha.rotate(angle, expand=True, resample=Image.Resampling.NEAREST, fillcolor=0)
        a_r = a_r.point(lambda v: 255 if v > 180 else 0)
        # fixed-ish opacity
        a_r = a_r.point(lambda v: int(v * 0.7) if v else 0)
        stain = rgb_r.convert("RGBA")
        stain.putalpha(a_r)
        nw, nh = stain.size
        x = rng.randint(-nw // 5, max(0, w - nw * 4 // 5))
        y = rng.randint(-nh // 5, max(0, h - nh * 4 // 5))
        layer = Image.new("RGBA", out.size, (0, 0, 0, 0))
        layer.paste(stain, (x, y), stain)
        out = Image.alpha_composite(out, layer)
    return out.convert("RGB")


def _ink_color(rng: random.Random) -> tuple[int, int, int]:
    # dark readable ink on light paper
    base = 22 + rng.randint(0, 6)
    return (base + 6, base + 3, base)


def _draw_text_messy(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font,
    fill,
    rng: random.Random,
    max_jitter: float = 1.8,
) -> None:
    x, y = xy
    # slight per-character jitter for "not perfectly neat"
    for ch in text:
        jx = rng.uniform(-max_jitter, max_jitter)
        jy = rng.uniform(-max_jitter * 0.6, max_jitter * 0.6)
        draw.text((x + jx, y + jy), ch, font=font, fill=fill)
        x += _size(draw, ch, font)[0]


def _draw_lines_messy(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    xy: tuple[int, int],
    font,
    fill,
    line_h: int,
    rng: random.Random,
    width: int | None = None,
    align: str = "left",
    max_jitter: float = 1.6,
    drunk: bool = False,
) -> None:
    x0, y = xy
    for line in lines:
        xx = x0
        if width and align != "left":
            w = _size(draw, line, font)[0]
            xx = x0 + (width - w if align == "right" else (width - w) // 2)
        if drunk:
            xx += int(rng.uniform(-2.5, 2.5))
            yy = y + int(rng.uniform(-1.2, 1.2))
            _draw_text_messy(draw, line, (xx, yy), font, fill, rng, max_jitter)
            y += line_h + int(rng.uniform(-0.8, 1.5))
        else:
            # straight, sober text
            draw.text((xx, y), line, font=font, fill=fill)
            y += line_h


def _media_path(value: object, root: Path) -> Path | None:
    if not value:
        return None
    raw = Path(str(value))
    p = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if p.parent != root or not p.name.startswith("media_") or not p.is_file():
        return None
    return p


def _thin_panel(
    content: Image.Image,
    s: float,
    width: int | None = None,
    dim: bool = True,
) -> Image.Image:
    """Closed thin frame like light theme blocks + optional inner dim."""
    if content.mode != "RGBA":
        content = content.convert("RGBA")
    cw, ch = content.size
    border = max(2, int(2.2 * s))
    pad = max(6, int(8 * s))
    out_w = width if width is not None else cw
    inner_w = out_w - border * 2
    # fit content width into panel
    if cw > inner_w and cw > 0:
        scale = inner_w / cw
        content = content.resize((max(1, int(cw * scale)), max(1, int(ch * scale))), Image.Resampling.LANCZOS)
        cw, ch = content.size
    out_h = ch + border * 2 + pad * 2
    out = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    if dim:
        dim_layer = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
        dd = ImageDraw.Draw(dim_layer)
        dd.rectangle(
            (border, border, out_w - border - 1, out_h - border - 1),
            fill=(35, 26, 16, 40),
        )
        out = Image.alpha_composite(out, dim_layer)
    d = ImageDraw.Draw(out)
    # closed border all sides
    for i in range(border):
        d.rectangle((i, i, out_w - 1 - i, out_h - 1 - i), outline=(28, 22, 16, 220))
    ox = (out_w - cw) // 2
    oy = border + pad
    out.paste(content, (ox, oy), content)
    return out


def _frame_panel(content: Image.Image, s: float, width: int | None = None, pad: int | None = None) -> Image.Image:
    # alias kept for compatibility
    return _thin_panel(content, s, width=width, dim=True)


def _stack_blocks(blocks: list[Image.Image], width: int) -> Image.Image:
    if not blocks:
        return Image.new("RGBA", (width, 1), (0, 0, 0, 0))
    h = sum(b.height for b in blocks)
    out = Image.new("RGBA", (width, max(1, h)), (0, 0, 0, 0))
    y = 0
    for b in blocks:
        out.paste(b, (0, y), b if b.mode == "RGBA" else None)
        y += b.height
    return out


def render_olddoc(
    page: Page,
    work_dir: str | Path,
    quality: str,
    output: str | Path,
    watermark: bool = True,
) -> Path:
    root = Path(work_dir).resolve()
    path = Path(output).resolve()
    theme = get_theme("olddoc")
    tpl = get_template(page.type)
    data = ensure_old_meta(dict(page.data))
    page.data = data  # keep seed stable for this render session
    seed = int(data["_old_seed"])
    stain_count = int(data.get("_old_stain_count", 1) or 0)
    if not bool(data.get("_old_stains", True)):
        stain_count = 0
    paper_index = int(data.get("_old_paper", 0) or 0) % max(1, paper_count())
    substances = bool(data.get("_old_substances", False))
    drunk = bool(data.get("_old_drunk", False)) or substances
    drunk_flags = bool(data.get("_old_drunk_flags", False)) or substances
    show_window = bool(data.get("_old_window", True))
    show_outline = bool(data.get("_old_outline", True))
    rng = _rng(seed)

    def draw_lines(draw, lines, xy, font, fill, line_h, width=None, align="left", max_jitter=1.6):
        j = max_jitter * (2.4 if substances else 1.0)
        _draw_lines_messy(draw, lines, xy, font, fill, line_h, rng, width, align, j, drunk=drunk)

    s = SCALE.get(quality, SCALE["high"])
    card_w = int(780 * s)
    pad = int(36 * s)
    content_w = card_w - pad * 2
    ink = _ink_color(rng)
    ink_sec = tuple(min(255, c + 40) for c in ink)
    sep = tuple(min(255, c + 70) for c in ink)

    header_parts: list[Image.Image] = []
    media_parts: list[Image.Image] = []
    info_parts: list[Image.Image] = []
    foot_parts: list[Image.Image] = []
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    # --- header ---
    kind_font = _serif(max(13, int(15 * s)), bold=True)
    title_font = _serif(max(26, int(34 * s)), bold=True)
    sub_font = _serif(max(14, int(17 * s)), italic=True)
    title = data.get("title") or page.title or "Без названия"
    subtitle = data.get(tpl.subtitle_key, "") if tpl.subtitle_key else ""
    kind = tpl.label.upper()
    kind_lines = _wrap(tmp, kind, kind_font, content_w)
    title_lines = _wrap(tmp, title, title_font, content_w)
    sub_lines = _wrap(tmp, subtitle, sub_font, content_w) if subtitle else []
    kh, th, sh = _line_h(tmp, kind_font), _line_h(tmp, title_font), _line_h(tmp, sub_font)
    hh = pad // 2 + len(kind_lines) * kh + 8 + len(title_lines) * th
    if sub_lines:
        hh += 6 + len(sub_lines) * sh
    hh += pad // 2
    header = Image.new("RGBA", (card_w, hh), (0, 0, 0, 0))
    hd = ImageDraw.Draw(header)
    y = pad // 2
    draw_lines(hd, kind_lines, (pad, y), kind_font, sep, kh, content_w, "center", 1.2)
    y += len(kind_lines) * kh + 8
    draw_lines(hd, title_lines, (pad, y), title_font, ink, th, content_w, "center", 2.0)
    y += len(title_lines) * th
    if sub_lines:
        y += 6
        draw_lines(hd, sub_lines, (pad, y), sub_font, ink_sec, sh, content_w, "center", 1.4)
    header_parts.append(header)

    # --- images ---
    battle_flags1: list[tuple[Path, str]] = []
    battle_flags2: list[tuple[Path, str]] = []

    def resolve_item(item: tuple[str, str] | None) -> tuple[Path, str] | None:
        if not item:
            return None
        mp = _media_path(item[0], root)
        return (mp, item[1]) if mp else None

    def resolve_items(items: list[tuple[str, str]]) -> list[tuple[Path, str]]:
        out: list[tuple[Path, str]] = []
        for value, cap in items:
            mp = _media_path(value, root)
            if mp:
                out.append((mp, cap))
        return out

    def gallery_block(media_items: list[tuple[Path, str]], *, tilt: bool = False) -> Image.Image | None:
        if not media_items:
            return None
        gap = int(10 * s)
        cell_w = content_w if len(media_items) == 1 else (content_w - gap) // 2
        max_h = int(320 * s)
        prepared = []
        for mp, cap in media_items:
            try:
                src = ImageOps.exif_transpose(Image.open(mp))
                src.load()
                src.thumbnail((cell_w, max_h), Image.Resampling.LANCZOS)
                if src.mode != "RGBA":
                    src = src.convert("RGBA")
                prepared.append((src, cap))
            except Exception:
                continue
        if not prepared:
            return None

        cap_font = _serif(max(12, int(14 * s)), italic=True)
        lh = _line_h(tmp, cap_font)
        cols = 1 if len(prepared) == 1 else 2
        rows = [prepared[i : i + cols] for i in range(0, len(prepared), cols)]
        heights = []
        for row in rows:
            rh = 0
            for src, cap in row:
                ch = src.height
                if cap:
                    ch += int(6 * s) + len(_wrap(tmp, cap, cap_font, cell_w - 8)) * lh
                rh = max(rh, ch)
            heights.append(rh)

        gh = pad // 2 + sum(heights) + gap * (len(rows) - 1) + pad // 2
        gal = Image.new("RGBA", (card_w, gh), (0, 0, 0, 0))
        gd = ImageDraw.Draw(gal)
        yy = pad // 2
        for row, rh in zip(rows, heights):
            for i, (src, cap) in enumerate(row):
                if len(row) == 1:
                    cell_x = pad
                    this_w = content_w
                else:
                    cell_x = pad + i * (cell_w + gap)
                    this_w = cell_w
                cx = cell_x + (this_w - src.width) // 2
                paste_y = yy
                if tilt:
                    ang = rng.uniform(-8.0, 8.0) if substances else rng.uniform(-3.5, 3.5)
                    rgb = src.convert("RGB")
                    alpha = src.split()[3] if src.mode == "RGBA" else Image.new("L", src.size, 255)
                    rgb_r = rgb.rotate(ang, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0))
                    a_r = alpha.rotate(ang, expand=True, resample=Image.Resampling.NEAREST, fillcolor=0)
                    a_r = a_r.point(lambda v: 255 if v > 200 else 0)
                    rotated = rgb_r.convert("RGBA")
                    rotated.putalpha(a_r)
                    ox = cx + rng.randint(-2, 2) - (rotated.width - src.width) // 2
                    oy = yy + rng.randint(-2, 2) - (rotated.height - src.height) // 2
                    gal.paste(rotated, (ox, oy), rotated)
                else:
                    gal.paste(src, (cx, paste_y), src)
                if cap:
                    lines = _wrap(tmp, cap, cap_font, this_w - 8)
                    draw_lines(
                        gd, lines, (cell_x + 4, yy + src.height + int(6 * s)),
                        cap_font, ink_sec, lh, this_w - 8, "center", 1.0,
                    )
            yy += rh + gap
        return gal

    media_items: list[tuple[Path, str]] = []
    if page.type == "battle":
        main_item, side1_items, side2_items, extra_items = battle_image_groups(data)
        main = resolve_item(main_item)
        if main:
            media_items.append(main)
        battle_flags1 = resolve_items(side1_items)
        battle_flags2 = resolve_items(side2_items)
        # Flags belong to conflict-side rows, never to the normal image gallery.
        media_items.extend(resolve_items(extra_items))
    else:
        for i, value in enumerate(page_images(data)):
            mp = _media_path(value, root)
            if mp:
                media_items.append((mp, image_caption(data, value, i)))

    gallery = gallery_block(media_items)
    if gallery:
        media_parts.append(gallery)

    # Territory maps are a separate media collection. Their captions must be
    # explicit: the main image's legacy caption must never leak onto a map.
    map_items: list[tuple[Path, str]] = []
    for value in map_images(data):
        mp = _media_path(value, root)
        if mp:
            map_items.append((mp, map_image_caption(data, value)))
    map_gallery = gallery_block(map_items)
    if map_gallery:
        media_parts.append(map_gallery)

    label_font = _serif(max(13, int(15 * s)), bold=True)
    value_font = _serif(max(13, int(15 * s)))
    sec_font = _serif(max(15, int(18 * s)), bold=True)
    lh_l = _line_h(tmp, label_font)
    lh_v = _line_h(tmp, value_font)

    def section_title(text: str) -> Image.Image:
        lines = _wrap(tmp, text, sec_font, content_w)
        lh = _line_h(tmp, sec_font)
        h = int(10 * s) + len(lines) * lh + int(8 * s)
        img = Image.new("RGBA", (card_w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        draw_lines(d, lines, (pad, int(10 * s)), sec_font, ink, lh, content_w, "left", 1.5)
        uy = h - int(6 * s)
        if drunk:
            d.line(
                (pad + rng.randint(-2, 2), uy, pad + content_w // 2 + rng.randint(-8, 16), uy + rng.randint(-1, 1)),
                fill=sep,
                width=max(1, int(s)),
            )
        else:
            d.line((pad, uy, pad + int(content_w * 0.42), uy), fill=sep, width=max(1, int(s)))
        return img

    def field_row(label: str, value: object) -> Image.Image:
        lab_lines = _wrap(tmp, label, label_font, int(content_w * 0.38))
        val_lines = _wrap(tmp, value, value_font, int(content_w * 0.55))
        h = max(len(lab_lines) * lh_l, len(val_lines) * lh_v) + int(12 * s)
        img = Image.new("RGBA", (card_w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        col1 = int(content_w * 0.38)
        draw_lines(d, lab_lines, (pad, int(6 * s)), label_font, ink_sec, lh_l, col1, "left", 1.4)
        draw_lines(
            d,
            val_lines,
            (pad + col1 + int(12 * s), int(6 * s)),
            value_font,
            ink,
            lh_v,
            int(content_w * 0.55),
            "left",
            1.5,
        )
        return img

    def _battle_parts(value: object) -> list[str]:
        if value in (None, "", []):
            return ["—"]
        if isinstance(value, (list, tuple)):
            return [str(x).strip() for x in value if str(x).strip()] or ["—"]
        return [line.strip() for line in str(value).splitlines() if line.strip()] or ["—"]

    def _battle_flag_thumb(path: Path, size: tuple[int, int]) -> Image.Image | None:
        try:
            src = ImageOps.exif_transpose(Image.open(path))
            src.load()
            src = ImageOps.fit(src.convert("RGBA"), size, Image.Resampling.LANCZOS)
        except Exception:
            return None
        if drunk_flags:
            ang = rng.uniform(-8.0, 8.0) if substances else rng.uniform(-3.5, 3.5)
            src = src.rotate(ang, expand=True, resample=Image.Resampling.BICUBIC)
        return src

    def battle_side_grid(left: object, right: object) -> Image.Image:
        col_w = content_w // 2
        inner_pad = max(8, int(10 * s))
        pad_y = max(6, int(8 * s))
        row_gap = max(4, int(5 * s))
        flag_size = (max(22, int(30 * s)), max(14, int(19 * s)))
        gap = max(5, int(7 * s))
        font = value_font
        line_h = lh_v

        def side_rows(value: object, flags: list[tuple[Path, str]]):
            parts = _battle_parts(value)
            part_keys = {x.casefold().replace("ё", "е").strip() for x in parts}
            named = {}
            fallback = []
            for fp, cap in flags:
                thumb = _battle_flag_thumb(fp, flag_size)
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
                lines = _wrap(tmp, part, font, max(40, col_w - inner_pad * 2 - reserve))
                row_h = max(len(lines) * line_h, thumb.height if thumb is not None else 0, line_h)
                rows.append((thumb, lines, row_h))
            return rows

        left_rows = side_rows(left, battle_flags1)
        right_rows = side_rows(right, battle_flags2)

        def total_h(rows) -> int:
            return sum(rh for _thumb, _lines, rh in rows) + row_gap * max(0, len(rows) - 1)

        h = max(total_h(left_rows), total_h(right_rows)) + pad_y * 2
        img = Image.new("RGBA", (card_w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        divider_x = pad + col_w
        d.line((divider_x, pad_y // 2, divider_x, h - pad_y // 2), fill=sep, width=max(1, int(s)))

        def paint(rows, x0: int, mirror: bool) -> None:
            y = pad_y
            for thumb, lines, row_h in rows:
                x = x0 + inner_pad
                if thumb is not None:
                    fy = y + max(0, (row_h - thumb.height) // 2)
                    img.paste(thumb, (x, fy), thumb)
                    d.rectangle((x, fy, x + thumb.width - 1, fy + thumb.height - 1), outline=sep, width=max(1, int(s)))
                    x += thumb.width + gap
                text_w = max(30, x0 + col_w - inner_pad - x)
                ty = y + max(0, (row_h - len(lines) * line_h) // 2)
                draw_lines(d, lines, (x, ty), font, ink, line_h, text_w, "left", 1.1)
                y += row_h + row_gap

        paint(left_rows, pad, False)
        paint(right_rows, pad + col_w, True)
        return img

    def battle_text_grid(left: object, right: object) -> Image.Image:
        col_w = content_w // 2
        inner_pad = max(8, int(10 * s))
        pad_y = max(6, int(8 * s))
        left_lines = _wrap(tmp, left if left not in (None, "", []) else "—", value_font, col_w - inner_pad * 2)
        right_lines = _wrap(tmp, right if right not in (None, "", []) else "—", value_font, col_w - inner_pad * 2)
        h = max(len(left_lines), len(right_lines)) * lh_v + pad_y * 2
        img = Image.new("RGBA", (card_w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        divider_x = pad + col_w
        d.line((divider_x, pad_y // 2, divider_x, h - pad_y // 2), fill=sep, width=max(1, int(s)))
        draw_lines(d, left_lines, (pad + inner_pad, pad_y), value_font, ink, lh_v, col_w - inner_pad * 2, "left", 1.2)
        draw_lines(d, right_lines, (pad + col_w + inner_pad, pad_y), value_font, ink, lh_v, col_w - inner_pad * 2, "left", 1.2)
        return img

    skip = {"card_type_label", "title", "description", "image_caption"}
    if tpl.subtitle_key:
        skip.add(tpl.subtitle_key)
    sections_order = []
    for f in tpl.fields:
        if f.key not in skip and f.section not in sections_order:
            sections_order.append(f.section)

    battle_pairs = {
        "Командующие": ("commander_1", "commander_2"),
        "Силы сторон": ("strength_1", "strength_2"),
        "Потери": ("losses_1", "losses_2"),
    }

    for sec_name in sections_order:
        fields = [f for f in tpl.fields if f.section == sec_name and f.key not in skip and data.get(f.key) not in (None, "", [])]
        if not fields:
            continue

        if page.type == "battle" and sec_name == "Противники":
            left = data.get("side_1")
            right = data.get("side_2")
            if left not in (None, "", []) or right not in (None, "", []):
                info_parts.append(section_title(sec_name))
                info_parts.append(battle_side_grid(left, right))
            continue

        if page.type == "battle" and sec_name in battle_pairs:
            left_key, right_key = battle_pairs[sec_name]
            left = data.get(left_key)
            right = data.get(right_key)
            if left not in (None, "", []) or right not in (None, "", []):
                info_parts.append(section_title(sec_name))
                info_parts.append(battle_text_grid(left, right))
            # Preserve any non-column fields in the same section (e.g. civilian casualties).
            for f in fields:
                if f.key not in (left_key, right_key):
                    if not (left not in (None, "", []) or right not in (None, "", [])) and f == fields[0]:
                        info_parts.append(section_title(sec_name))
                    info_parts.append(field_row(f.label, data[f.key]))
            continue

        info_parts.append(section_title(sec_name))
        for f in fields:
            info_parts.append(field_row(f.label, data[f.key]))

    custom = [x for x in data.get("custom_fields") or [] if isinstance(x, dict) and x.get("value") not in (None, "")]
    if custom:
        info_parts.append(section_title("Дополнительные сведения"))
        for x in custom:
            info_parts.append(field_row(str(x.get("name", "Поле")), x.get("value", "")))

    for sec in data.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        rows = [x for x in sec.get("fields") or [] if isinstance(x, dict) and x.get("value") not in (None, "")]
        if not rows:
            continue
        info_parts.append(section_title(str(sec.get("title") or "Раздел")))
        for x in rows:
            info_parts.append(field_row(str(x.get("name", "Поле")), x.get("value", "")))

    if data.get("description"):
        info_parts.append(section_title("Описание"))
        desc_font = _serif(max(13, int(15 * s)))
        lines = _wrap(tmp, data["description"], desc_font, content_w)
        lh = _line_h(tmp, desc_font)
        h = int(8 * s) + len(lines) * lh + int(12 * s)
        img = Image.new("RGBA", (card_w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        draw_lines(d, lines, (pad, int(8 * s)), desc_font, ink, lh, content_w, "left", 1.3)
        info_parts.append(img)

    if watermark:
        wf = _serif(max(11, int(12 * s)), italic=True)
        h = int(28 * s)
        img = Image.new("RGBA", (card_w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        draw_lines(d, ["INFOBOX BOT"], (pad, int(6 * s)), wf, sep, _line_h(tmp, wf), content_w, "right", 1.0)
        foot_parts.append(img)

    gap_y = int(10 * s)
    body: list[Image.Image] = []
    body.extend(header_parts)

    if media_parts:
        media_img = _stack_blocks(media_parts, card_w)
        if show_window:
            media_img = _thin_panel(media_img, s, width=card_w, dim=True)
        body.append(media_img)
        body.append(Image.new("RGBA", (card_w, gap_y), (0, 0, 0, 0)))

    if info_parts:
        info_img = _stack_blocks(info_parts, card_w)
        if show_window:
            info_img = _thin_panel(info_img, s, width=card_w, dim=True)
        body.append(info_img)

    body.extend(foot_parts)

    content_h = sum(b.height for b in body)
    margin = int(36 * s)
    total_w = card_w + margin * 2
    total_h = content_h + margin * 2

    bg = _paper_bg(total_w, total_h, rng, paper_index=paper_index)
    canvas = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    yy = margin
    for b in body:
        canvas.paste(b, (margin, yy), b if b.mode == "RGBA" else None)
        yy += b.height

    composed = Image.alpha_composite(bg.convert("RGBA"), canvas)
    if stain_count > 0:
        composed = _apply_stains(composed.convert("RGB"), rng, count=stain_count).convert("RGBA")
    if substances:
        wash = ImageEnhance.Color(composed.convert("RGB")).enhance(1.08)
        wash = ImageEnhance.Contrast(wash).enhance(1.06)
        composed = wash.convert("RGBA")

    depth = int(16 * s) + rng.randint(3, 10)
    mask = _torn_mask(total_w, total_h, rng, depth=depth)
    paper = composed.convert("RGBA")
    r, g, b, a = paper.split()
    a = Image.composite(a, Image.new("L", paper.size, 0), mask)
    paper = Image.merge("RGBA", (r, g, b, a))

    pad_out = max(14, int(7 * s) + 6)
    final = Image.new("RGBA", (total_w + pad_out * 2, total_h + pad_out * 2), (0, 0, 0, 0))
    if show_outline:
        stroke_w = max(2, int(2.8 * s))
        outline = _paper_outline(mask, width=stroke_w, color=(36, 26, 16, 235))
        final.paste(outline, (pad_out, pad_out), outline)
    final.paste(paper, (pad_out, pad_out), paper)
    if bool(data.get("_old_bw", False)):
        # full B&W
        r, g, b, a = final.split()
        gray = Image.merge("RGB", (r, g, b)).convert("L")
        final = Image.merge("RGBA", (gray, gray, gray, a))
    final.save(path, "PNG", compress_level=6, dpi=(144, 144))
    return path
