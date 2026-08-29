"""Каталог шрифтов: 10 семейств в корне + пользовательские."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Ровно 10 семейств
_FAMILIES_ORDER = [
    ("default", "По умолчанию (тема)"),
    ("dejavu-sans", "DejaVu Sans"),
    ("dejavu-mono", "DejaVu Mono"),
    ("liberation-serif", "Liberation Serif"),
    ("pixeloid-sans", "Pixeloid Sans"),
    ("isaac", "Isaac"),
    ("roboto", "Roboto"),
    ("noto-sans", "Noto Sans"),
    ("pt-sans", "PT Sans"),
    ("inter", "Inter"),
    ("pt-serif", "PT Serif"),
]
# default + 10 = 11 entries in list - user said 10 fonts
# reinterpret: 10 selectable fonts total including or excluding default?
# "оставь 10" = 10 fonts. Keep default as option + 9, or 10 real fonts + default.
# I'll keep default + 10 named fonts (11 choices) OR strictly 10 including default.
# Strict: default + 9 others = 10 total choices
_FAMILIES_ORDER = [
    ("default", "По умолчанию (тема)"),
    ("dejavu-sans", "DejaVu Sans"),
    ("liberation-serif", "Liberation Serif"),
    ("pixeloid-sans", "Pixeloid Sans"),
    ("isaac", "Isaac"),
    ("roboto", "Roboto"),
    ("noto-sans", "Noto Sans"),
    ("pt-sans", "PT Sans"),
    ("inter", "Inter"),
    ("pt-serif", "PT Serif"),
]


def _exists_family(key: str) -> bool:
    if key == "default":
        return True
    reg, _ = resolve_font_files(key)
    return reg is not None and reg.is_file()


def list_bundled_families() -> list[tuple[str, str]]:
    out = []
    for key, name in _FAMILIES_ORDER:
        if key == "default" or _exists_family(key):
            out.append((key, name))
    return out


def resolve_font_files(family_key: str) -> tuple[Path | None, Path | None]:
    if not family_key or family_key == "default":
        return None, None
    mapping = {
        "dejavu-sans": (ROOT / "DejaVuSans.ttf", ROOT / "DejaVuSans-Bold.ttf"),
        "dejavu-mono": (ROOT / "DejaVuSansMono.ttf", ROOT / "DejaVuSansMono-Bold.ttf"),
        "liberation-serif": (ROOT / "LiberationSerif-Regular.ttf", ROOT / "LiberationSerif-Bold.ttf"),
        "pixeloid-sans": (ROOT / "PixeloidSans.otf", ROOT / "PixeloidSans-Bold.otf"),
        "isaac": (ROOT / "ISAACFONTDESCRIPTIONENGRUS-FILL_0.TTF", ROOT / "ISAACFONTDESCRIPTIONENGRUS-FILL_0.TTF"),
        "roboto": (ROOT / "gf-roboto-400.ttf", ROOT / "gf-roboto-700.ttf"),
        "noto-sans": (ROOT / "gf-noto-sans-400.ttf", ROOT / "gf-noto-sans-700.ttf"),
        "pt-sans": (ROOT / "gf-pt-sans-400.ttf", ROOT / "gf-pt-sans-700.ttf"),
        "inter": (ROOT / "gf-inter-400.ttf", ROOT / "gf-inter-700.ttf"),
        "pt-serif": (ROOT / "gf-pt-serif-400.ttf", ROOT / "gf-pt-serif-700.ttf"),
    }
    pair = mapping.get(family_key)
    if not pair:
        # fallback gf-
        reg = ROOT / f"gf-{family_key}-400.ttf"
        bold = ROOT / f"gf-{family_key}-700.ttf"
        if reg.is_file():
            return reg, bold if bold.is_file() else reg
        return None, None
    reg, bold = pair
    if not reg.is_file():
        return None, None
    if not bold.is_file():
        bold = reg
    return reg, bold


def user_fonts_dir(work_dir: str | Path, user_id: int) -> Path:
    d = Path(work_dir).resolve() / "user_fonts" / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_user_fonts(work_dir: str | Path, user_id: int) -> list[tuple[str, str]]:
    d = user_fonts_dir(work_dir, user_id)
    out = []
    for p in sorted(d.glob("*")):
        if p.suffix.lower() in {".ttf", ".otf"} and p.stat().st_size > 1000:
            out.append((f"user:{p.name}", f"Свой: {p.stem}"))
    return out


def resolve_user_font(work_dir: str | Path, user_id: int, key: str) -> Path | None:
    if not key.startswith("user:"):
        return None
    p = user_fonts_dir(work_dir, user_id) / key[5:]
    if p.is_file() and p.suffix.lower() in {".ttf", ".otf"}:
        return p
    return None


def all_font_choices(work_dir: str | Path, user_id: int | None) -> list[tuple[str, str]]:
    items = list_bundled_families()
    if user_id is not None:
        items.extend(list_user_fonts(work_dir, user_id))
    return items


def numbered_font_choices(work_dir: str | Path, user_id: int | None) -> list[tuple[int, str, str]]:
    return [(i + 1, k, n) for i, (k, n) in enumerate(all_font_choices(work_dir, user_id))]


def search_fonts(work_dir: str | Path, user_id: int | None, query: str) -> list[tuple[int, str, str]]:
    items = numbered_font_choices(work_dir, user_id)
    q = (query or "").strip()
    if not q:
        return items
    if q.isdigit():
        n = int(q)
        return [x for x in items if x[0] == n]
    low = q.casefold().replace("ё", "е")
    return [
        x for x in items
        if low in x[2].casefold().replace("ё", "е") or low in x[1].casefold()
    ]


def font_css_for_family(family_key: str, work_dir: str | Path = ".", user_id: int | None = None) -> str:
    if not family_key or family_key == "default":
        return ""
    import base64

    if family_key.startswith("user:") and user_id is not None:
        path = resolve_user_font(work_dir, user_id, family_key)
        if not path:
            return ""
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        fmt = "opentype" if path.suffix.lower() == ".otf" else "truetype"
        return (
            f"@font-face{{font-family:'UserFont';src:url('data:font/{fmt};base64,{data}') format('{fmt}');"
            f"font-weight:400 700;font-style:normal;font-display:block}}"
        )
    reg, bold = resolve_font_files(family_key)
    if not reg:
        return ""
    parts = []
    for path, weight in ((reg, 400), (bold or reg, 700)):
        if not path or not path.is_file():
            continue
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        fmt = "opentype" if path.suffix.lower() == ".otf" else "truetype"
        parts.append(
            f"@font-face{{font-family:'CustomCard';src:url('data:font/{fmt};base64,{data}') format('{fmt}');"
            f"font-weight:{weight};font-style:normal;font-display:block}}"
        )
    return "\n".join(parts)


def css_family_name(family_key: str) -> str:
    if not family_key or family_key == "default":
        return ""
    if family_key.startswith("user:"):
        return "UserFont"
    return "CustomCard"
