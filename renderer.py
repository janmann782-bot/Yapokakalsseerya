from __future__ import annotations

import asyncio
import base64
import html
import logging
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from media import battle_image_groups, image_caption, map_image_caption, map_images, page_images, parliament_image_assets
from models import Page
from templates import Field, Template, get_template
from themes import Theme, get_theme
from fonts_catalog import css_family_name, font_css_for_family

QUALITY_SCALE = {"standard": 1.5, "high": 2.0, "ultra": 2.5}
_render_slots = asyncio.Semaphore(2)
log = logging.getLogger(__name__)


def esc(x: object) -> str:
    return html.escape(str(x), quote=True)


def value_html(x: object) -> str:
    if isinstance(x, (list, tuple)):
        x = "\n".join(str(i) for i in x)
    return esc(x).replace("\n", "<br>")


def image_uri(path: str | Path | None, work_dir: str | Path) -> str | None:
    if not path:
        return None

    root = Path(work_dir).resolve()
    raw = Path(path)
    p = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if p.parent != root or not p.name.startswith("media_") or not p.is_file():
        return None

    mime = "image/webp"
    if p.suffix.lower() in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif p.suffix.lower() == ".png":
        mime = "image/png"
    raw = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{raw}"


@lru_cache(maxsize=1)
def font_css() -> str:
    root = Path(__file__).resolve().parent

    def find_font(name: str) -> Path | None:
        candidates = (
            root / name,
            Path("/usr/share/fonts/truetype/liberation") / name,
            Path("/usr/local/share/fonts") / name,
            Path("C:/Windows/Fonts") / name,
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    fonts = (
        ("Isaac Fill", "ISAACFONTDESCRIPTIONENGRUS-FILL_0.TTF", 400),
        ("Wikipedia Sans", "LiberationSans-Regular.ttf", 400),
        ("Wikipedia Sans", "LiberationSans-Bold.ttf", 700),
        ("Wikipedia Serif", "LiberationSerif-Regular.ttf", 400),
        ("Wikipedia Serif", "LiberationSerif-Bold.ttf", 700),
        ("InfoBox Mono", "LiberationMono-Regular.ttf", 400),
        ("InfoBox Mono", "LiberationMono-Bold.ttf", 700),
    )
    out = []
    for family, name, weight in fonts:
        p = find_font(name)
        if p is None:
            continue
        raw = base64.b64encode(p.read_bytes()).decode("ascii")
        out.append(
            f"@font-face{{font-family:'{family}';src:url(data:font/ttf;base64,{raw}) "
            f"format('truetype');font-style:normal;font-weight:{weight};}}"
        )
    return "".join(out)




def battle_media(data: dict, work_dir: str | Path) -> tuple[tuple[str, str] | None, list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str]]]:
    main_item, side1_items, side2_items, extra_items = battle_image_groups(data)

    def to_uri_list(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
        out = []
        for path, cap in items:
            uri = image_uri(path, work_dir)
            if uri:
                out.append((uri, cap))
        return out

    main = None
    if main_item:
        uri = image_uri(main_item[0], work_dir)
        if uri:
            main = (uri, main_item[1])
    extras = []
    for path, caption in extra_items:
        uri = image_uri(path, work_dir)
        if uri:
            extras.append((uri, caption))
    return main, to_uri_list(side1_items), to_uri_list(side2_items), extras


def battle_side_cell(value: object, flags: list[tuple[str, str]], mirror: bool = False) -> str:
    """Wikipedia-like conflict cell: compact rows with the flag before the member name."""
    if value in (None, '', []):
        parts = ["—"]
    elif isinstance(value, (list, tuple)):
        parts = [str(x).strip() for x in value if str(x).strip()] or ["—"]
    else:
        parts = [ln.strip() for ln in str(value).splitlines() if ln.strip()] or ["—"]

    part_keys = {p.casefold().replace("ё", "е").strip() for p in parts}
    named = {
        cap.casefold().replace("ё", "е").strip(): uri
        for uri, cap in flags
        if uri and str(cap).strip() and cap.casefold().replace("ё", "е").strip() in part_keys
    }
    fallback_uris = [
        uri for uri, cap in flags
        if uri and (not str(cap).strip() or cap.casefold().replace("ё", "е").strip() not in part_keys)
    ]
    fallback_slots = [i for i, p in enumerate(parts) if p.casefold().replace("ё", "е").strip() not in named]
    fallback_targets = set(fallback_slots[-len(fallback_uris):]) if fallback_uris else set()
    fallback_iter = iter(fallback_uris)

    row_cls = "side-row side-row-mirror" if mirror else "side-row"
    rows_html = []
    for i, part in enumerate(parts):
        key = part.casefold().replace("ё", "е").strip()
        uri = named.get(key)
        if uri is None and i in fallback_targets:
            uri = next(fallback_iter, None)
        flag_html = f'<img class="mini-flag" src="{uri}" alt="">' if uri else ""
        text_html = f'<div class="battle-text">{value_html(part)}</div>'
        rows_html.append(f'<div class="{row_cls}">{flag_html}{text_html}</div>')
    cell_cls = "battle-cell battle-side-name battle-side-mirror" if mirror else "battle-cell battle-side-name"
    return f'<div class="{cell_cls}">' + "".join(rows_html) + "</div>"


def battle_text_cell(value: object) -> str:
    if value in (None, '', []):
        value = '—'
    return f'<div class="battle-cell"><div class="battle-text">{value_html(value)}</div></div>'


def battle_side_section(title: str, left: object, right: object, flags1: list[tuple[str, str]], flags2: list[tuple[str, str]]) -> str:
    if left in (None, '', []) and right in (None, '', []):
        return ''
    return (
        f'<section><h2>{esc(title)}</h2>'
        '<div class="battle-table">'
        f'{battle_side_cell(left, flags1, mirror=False)}'
        f'{battle_side_cell(right, flags2, mirror=True)}'
        '</div></section>'
    )


def battle_two_col_section(title: str, left: object, right: object) -> str:
    if left in (None, '', []) and right in (None, '', []):
        return ''
    return (
        f'<section><h2>{esc(title)}</h2>'
        '<div class="battle-table">'
        f'{battle_text_cell(left)}'
        f'{battle_text_cell(right)}'
        '</div></section>'
    )


def battle_sections(data: dict, work_dir: str | Path) -> tuple[str, str]:
    main, flags1, flags2, extras = battle_media(data, work_dir)
    gallery = ''
    if main:
        img, caption = main
        cap = f"<figcaption>{value_html(caption)}</figcaption>" if caption else ''
        gallery = f'<div class="gallery single"><figure><img src="{img}" alt="">{cap}</figure></div>'

    top = []
    for label, key in (("Дата", "date"), ("Место", "place"), ("Итог", "result"), ("Территориальные изменения", "territorial_changes")):
        if data.get(key) not in (None, '', []):
            top.append(row(label, data[key]))

    body = ''.join(top)
    body += battle_side_section('Противники', data.get('side_1'), data.get('side_2'), flags1, flags2)
    body += battle_two_col_section('Командующие', data.get('commander_1'), data.get('commander_2'))
    body += battle_two_col_section('Силы сторон', data.get('strength_1'), data.get('strength_2'))
    body += battle_two_col_section('Потери', data.get('losses_1'), data.get('losses_2'))
    if data.get('casualties_civilian') not in (None, '', []):
        body += row('Жертвы среди гражданских', data['casualties_civilian'])

    # Extra battle images are intentionally not rendered inside the infobox.
    # A Wikipedia-style infobox is a compact summary: main image + map are enough.
    return gallery, body



PARLIAMENT_PALETTE = (
    "#5B8FF9", "#61DDAA", "#65789B", "#F6BD16", "#7262FD",
    "#78D3F8", "#9661BC", "#F6903D", "#008685", "#F08BB4",
)


def _norm_key(value: object) -> str:
    return str(value or "").casefold().replace("ё", "е").strip()


def _parse_int(value: object) -> int | None:
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
    named = raw.lower()
    allowed = {'red', 'green', 'blue', 'yellow', 'orange', 'purple', 'pink', 'gray', 'grey', 'black', 'white', 'brown'}
    return raw if named in allowed else fallback


def _parse_parliament_parties(value: object, total_seats: int | None = None) -> tuple[list[dict], int]:
    parties: list[dict] = []
    lines = []
    if isinstance(value, (list, tuple)):
        lines = [str(x).strip() for x in value if str(x).strip()]
    else:
        lines = [ln.strip() for ln in str(value or '').splitlines() if ln.strip()]

    for idx, raw in enumerate(lines):
        parts = [p.strip() for p in __import__('re').split(r'\s*[|;]\s*', raw) if p.strip()]
        name = ''
        seats = None
        color = ''
        if len(parts) >= 2:
            name = parts[0]
            seats = _parse_int(parts[1])
            if len(parts) >= 3:
                color = parts[2]
        else:
            m = __import__('re').match(r'^(.*?)\s+(\d+)\s*(#[0-9A-Fa-f]{3,6}|[A-Za-z]+)?\s*$', raw)
            if m:
                name = m.group(1).strip()
                seats = int(m.group(2))
                color = (m.group(3) or '').strip()
        if not name or not seats or seats <= 0:
            continue
        fallback = PARLIAMENT_PALETTE[idx % len(PARLIAMENT_PALETTE)]
        parties.append({
            'name': name,
            'seats': seats,
            'color': _safe_color(color, fallback),
        })
    total = total_seats or sum(int(x['seats']) for x in parties)
    return parties, total


def _hemicycle_counts(total: int) -> list[int]:
    if total <= 0:
        return []
    rows = 4 if total <= 40 else 5 if total <= 90 else 6 if total <= 160 else 7
    weights = [1.0 + i * 0.24 for i in range(rows)]
    raw = [total * w / sum(weights) for w in weights]
    counts = [max(1, int(x)) for x in raw]
    diff = total - sum(counts)
    order = list(range(rows - 1, -1, -1))
    i = 0
    while diff != 0:
        idx = order[i % len(order)]
        if diff > 0:
            counts[idx] += 1
            diff -= 1
        elif counts[idx] > 1:
            counts[idx] -= 1
            diff += 1
        i += 1
    return counts


def _parliament_svg(parties: list[dict], total: int) -> str:
    import math
    if total <= 0:
        return ''
    colors: list[str] = []
    for party in parties:
        colors.extend([party['color']] * int(party['seats']))
    if len(colors) < total:
        colors.extend(['#C8CCD1'] * (total - len(colors)))
    colors = colors[:total]
    counts = _hemicycle_counts(total)
    cx, base_y = 150.0, 126.0
    inner_r, step = 30.0, 15.5
    seat_r = 6.3 if total <= 60 else 5.5 if total <= 110 else 4.8 if total <= 170 else 4.2
    circles = []
    seat_i = 0
    for row_i, count in enumerate(counts):
        r = inner_r + step * row_i
        if count == 1:
            angles = [math.pi / 2]
        else:
            angles = [math.pi - (j + 0.5) * math.pi / count for j in range(count)]
        for ang in angles:
            x = cx + r * math.cos(ang)
            y = base_y - r * math.sin(ang)
            fill = colors[seat_i] if seat_i < len(colors) else '#C8CCD1'
            seat_i += 1
            circles.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{seat_r:.2f}" fill="{fill}" stroke="#202122" stroke-width="0.7" />')
    return '<svg class="parliament-svg" viewBox="0 0 300 150" aria-hidden="true">' + ''.join(circles) + '</svg>'


def parliament_block_html(data: dict, work_dir: str | Path) -> str:
    parties, total = _parse_parliament_parties(data.get('parliament_parties'), _parse_int(data.get('legislature_seats')))
    if not parties or total <= 0:
        return ''

    title = str(data.get('parliament_chart_title') or data.get('parliament') or data.get('legislature') or 'Парламент').strip()
    majority = _parse_int(data.get('parliament_majority')) or (total // 2 + 1)
    note = str(data.get('parliament_note') or '').strip()
    country = str(data.get('title') or '').strip()

    _, flag_item, logo_items = parliament_image_assets(data)
    flag_uri = image_uri(flag_item[0], work_dir) if flag_item else None
    logo_map = {}
    for path, party_name in logo_items:
        uri = image_uri(path, work_dir)
        if uri and party_name:
            logo_map[_norm_key(party_name)] = uri

    legend_rows = []
    for party in parties:
        seats = int(party['seats'])
        pct = seats / total * 100 if total else 0
        logo_uri = logo_map.get(_norm_key(party['name']))
        logo_html = f'<img class="party-logo" src="{logo_uri}" alt="">' if logo_uri else '<span class="party-logo party-logo-empty"></span>'
        legend_rows.append(
            '<div class="parliament-legend-row">'
            f'<span class="party-swatch" style="background:{esc(party["color"])}"></span>'
            f'{logo_html}'
            f'<span class="party-name">{esc(party["name"])}</span>'
            f'<span class="party-seats">{seats} · {pct:.1f}%</span>'
            '</div>'
        )

    bottom = ''
    if flag_uri or country:
        flag_html = f'<img class="parliament-flag" src="{flag_uri}" alt="">' if flag_uri else ''
        name_html = f'<div class="parliament-country">{esc(country)}</div>' if country else ''
        bottom = f'<div class="parliament-bottom">{flag_html}{name_html}</div>'

    meta = f'{total} мест · Большинство: {majority}'
    note_html = f'<div class="parliament-note">{value_html(note)}</div>' if note else ''
    return (
        '<section class="parliament-section"><h2>Состав парламента</h2>'
        '<div class="parliament-block">'
        f'<div class="parliament-title">{esc(title)}</div>'
        f'{_parliament_svg(parties, total)}'
        f'<div class="parliament-meta">{esc(meta)}</div>'
        f'<div class="parliament-legend">{"".join(legend_rows)}</div>'
        f'{bottom}'
        f'{note_html}'
        '</div></section>'
    )



def resolve_kind_label(tpl: Template, data: dict) -> str:
    value = str(data.get("card_type_label") or "").strip()
    if not value:
        return f"{tpl.emoji} {tpl.label}"
    low = value.casefold().replace("ё", "е").strip()
    if low in {"none", "hide", "hidden", "скрыть", "убрать", "нет", "off", "-"}:
        return ""
    return value.upper()


def row(label: str, value: object) -> str:
    return (
        '<div class="row">'
        f'<div class="label">{esc(label)}</div>'
        f'<div class="value">{value_html(value)}</div>'
        "</div>"
    )


def normal_section(title: str, fields: list[Field], data: dict) -> str:
    rows = [row(f.label, data[f.key]) for f in fields if data.get(f.key) not in (None, "", [])]
    if not rows:
        return ""
    return f'<section><h2>{esc(title)}</h2>{"".join(rows)}</section>'


def side_section(title: str, fields: list[Field], data: dict) -> str:
    cells = []
    for col in (1, 2):
        body = []
        for f in fields:
            if f.column == col and data.get(f.key) not in (None, "", []):
                body.append(
                    '<div class="side-item">'
                    f'<div class="side-label">{esc(f.label)}</div>'
                    f'<div>{value_html(data[f.key])}</div>'
                    "</div>"
                )
        cells.append(f'<div class="side-col">{"".join(body)}</div>')

    if not any(data.get(f.key) not in (None, "", []) for f in fields):
        return ""
    return f'<section><h2>{esc(title)}</h2><div class="side-grid">{"".join(cells)}</div></section>'


def custom_fields(data: dict) -> str:
    items = data.get("custom_fields") or []
    rows = [
        row(x.get("name", "Поле"), x.get("value", ""))
        for x in items
        if isinstance(x, dict) and x.get("value") not in (None, "")
    ]
    if not rows:
        return ""
    return f'<section><h2>Дополнительные сведения</h2>{"".join(rows)}</section>'


def custom_sections(data: dict) -> str:
    out = []
    for sec in data.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        rows = [
            row(x.get("name", "Поле"), x.get("value", ""))
            for x in sec.get("fields") or []
            if isinstance(x, dict) and x.get("value") not in (None, "")
        ]
        if rows:
            out.append(f'<section><h2>{esc(sec.get("title", "Раздел"))}</h2>{"".join(rows)}</section>')
    return "".join(out)


def standard_sections(tpl: Template, data: dict, work_dir: str | Path = ".") -> tuple[str, str]:
    if tpl.key == "battle":
        return battle_sections(data, work_dir)

    skip = {"card_type_label", "title", "description", "image_caption", "parliament_chart_title", "parliament_parties", "parliament_majority", "parliament_note"}
    if tpl.subtitle_key:
        skip.add(tpl.subtitle_key)

    names = []
    for f in tpl.fields:
        if f.key not in skip and f.section not in names:
            names.append(f.section)

    out = []
    for name in names:
        fields = [f for f in tpl.fields if f.section == name and f.key not in skip]
        if any(f.column for f in fields):
            out.append(side_section(name, fields, data))
        else:
            out.append(normal_section(name, fields, data))
    return "", "".join(out)


def stripe_rows(body: str) -> str:
    """Marks every second normal field row across the whole card, not per section."""
    marker = '<div class="row">'
    parts = body.split(marker)
    if len(parts) == 1:
        return body
    out = [parts[0]]
    for i, part in enumerate(parts[1:], start=1):
        cls = 'row row-alt' if i % 2 == 0 else 'row'
        out.append(f'<div class="{cls}">' + part)
    return ''.join(out)

def make_mirotorets_html(
    page: Page,
    theme: Theme,
    work_dir: str | Path = ".",
    watermark: bool = False,
) -> str:
    """Карточка точь-в-точь как на сайте Миротворец, без водяных знаков."""
    d = page.data
    title = str(d.get("title") or page.title or "").strip()
    birth = str(d.get("birth_date") or "").strip()
    country = str(d.get("country") or "Россия").strip()
    rank = str(d.get("rank") or "").strip()
    unit = str(d.get("unit") or "").strip()
    position = str(d.get("position") or "").strip()
    personal = str(d.get("personal_number") or "").strip()
    passport = str(d.get("passport") or "").strip()
    birth_place = str(d.get("birth_place") or "").strip()
    source = str(d.get("source") or "").strip()
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

    # верхний блок: только дата + страна (как на скрине)
    top_meta = []
    if birth:
        top_meta.append(
            f'<div class="top-line"><span class="tl">Дата рождения:</span> '
            f'<span class="tv">{esc(birth)}</span></div>'
        )
    if country:
        top_meta.append(
            f'<div class="top-line"><span class="tl">Страна:</span> '
            f'<span class="tv">{esc(country)}</span></div>'
            f'<div class="dash"></div>'
        )

    # основной текст: описание + поля в том же порядке что на скрине
    body_lines = []
    for line in desc.split("\n"):
        line = line.strip()
        if line:
            body_lines.append(f'<div class="line">{esc(line)}</div>')
    if unit:
        body_lines.append(
            f'<div class="line"><span class="lab">Подразделение:</span> {esc(unit)}</div>'
        )
    if position:
        body_lines.append(
            f'<div class="line"><span class="lab">Должность:</span> {esc(position)}</div>'
        )
    if rank:
        body_lines.append(
            f'<div class="line"><span class="lab">Звание:</span> {esc(rank)}</div>'
        )
    if personal:
        body_lines.append(
            f'<div class="line"><span class="lab">Личный номер:</span> {esc(personal)}</div>'
        )
    # дата рождения ещё раз в теле (как на оригинале)
    if birth:
        body_lines.append(
            f'<div class="line"><span class="lab">Дата рождения:</span> {esc(birth)}</div>'
        )
    if passport:
        body_lines.append(
            f'<div class="line"><span class="lab">Паспорт:</span> {esc(passport)}</div>'
        )
    if birth_place:
        body_lines.append(
            f'<div class="line"><span class="lab">Место рождения:</span> {esc(birth_place)}</div>'
        )
    if source:
        body_lines.append(f'<div class="line"><span class="lab">Источник:</span> {esc(source)}</div>')
    else:
        body_lines.append('<div class="line">Источник</div>')

    tags = [t for t in hashtags.split() if t.startswith("#")]
    tags_html = "".join(f'<div class="tag">{esc(t)}</div>' for t in tags)

    # одно фото слева или N/D
    photo_html = '<div class="nd">N/D</div>'
    imgs = page_images(d)
    if imgs:
        uri = image_uri(imgs[0], work_dir)
        if uri:
            photo_html = f'<img class="photo" src="{uri}" alt="">'

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; font-src data:; style-src 'unsafe-inline'">
<style>
{font_css()}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{
  background: #f4f6f9;
  color: #1a1a1a;
  font-family: 'DejaVu Sans', Arial, Helvetica, sans-serif;
}}
body {{ padding: 16px; }}
.card {{
  width: 780px;
  margin: 0 auto;
  background: #fff;
  border: 1px solid #b8c0cc;
  overflow: hidden;
}}
.header {{
  height: 36px;
  background: #1a5fb4;
  display: flex;
  align-items: center;
  padding: 0 14px;
}}
.hdr-name {{
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}
.top-row {{
  display: flex;
  gap: 0;
  border-bottom: 1px solid #c5cdd8;
  background: #fff;
}}
.icon-box {{
  width: 128px;
  flex: 0 0 128px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-right: 1px solid #c5cdd8;
  padding: 12px;
  background: #fff;
}}
.icon-box .photo {{
  display: block;
  width: 112px;
  height: 112px;
  object-fit: cover;
  border: 1px solid #c5cdd8;
  background: #f0f0f0;
}}
.icon-box .nd {{
  width: 112px;
  height: 112px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #c5cdd8;
  background: #f7f8fa;
  color: #666;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.06em;
}}
.meta-box {{
  flex: 1;
  padding: 16px 18px 14px;
  position: relative;
  background: #fff;
}}
.top-line {{
  font-size: 17px;
  line-height: 1.45;
  margin-bottom: 2px;
}}
.tl {{ color: #000; font-weight: 400; }}
.tv {{ color: #000; }}
.dash {{
  display: block;
  margin-top: 6px;
  border-bottom: 1px dashed #9aa3b0;
  width: 100%;
  height: 0;
}}
.body {{
  padding: 16px 20px 18px;
  background: #fff;
  font-size: 16.5px;
  line-height: 1.48;
}}
.name-line {{
  font-weight: 700;
  font-size: 17.5px;
  margin-bottom: 6px;
  color: #111;
}}
.line {{
  margin: 1px 0;
  color: #000;
}}
.lab {{ font-weight: 400; color: #000; }}
.tag {{
  color: #1a1a1a;
  margin: 2px 0;
}}
.footer-red {{
  margin-top: 14px;
  padding-top: 4px;
  color: #c41e3a;
  font-size: 14.5px;
  line-height: 1.42;
  font-weight: 500;
}}
</style>
</head>
<body>
<article class="card" id="infobox">
  <div class="header"><span class="hdr-name">{esc(title)}</span></div>
  <div class="top-row">
    <div class="icon-box">{photo_html}</div>
    <div class="meta-box">
      {"".join(top_meta)}
    </div>
  </div>
  <div class="body">
    {"".join(body_lines)}
    {tags_html}
    <div class="footer-red">{esc(footer_text)}</div>
  </div>
</article>
</body>
</html>"""


def make_html(
    page: Page,
    theme: Theme | None = None,
    work_dir: str | Path = ".",
    watermark: bool = True,
    font_key: str = "default",
    user_id: int | None = None,
) -> str:
    if page.type == "mirotorets" or (theme and theme.key == "mirotorets"):
        return make_mirotorets_html(page, theme or get_theme("mirotorets"), work_dir, watermark=False)

    tpl = get_template(page.type)
    theme = theme or get_theme(page.theme)
    d = page.data
    title = d.get("title") or page.title or "Без названия"
    subtitle = d.get(tpl.subtitle_key, "") if tpl.subtitle_key else ""
    description = d.get("description", "")

    gallery_extra, body = standard_sections(tpl, d, work_dir)

    gallery = gallery_extra
    if tpl.key != "battle":
        images = []
        for i, path in enumerate(page_images(d)):
            uri = image_uri(path, work_dir)
            if uri:
                images.append((uri, image_caption(d, path, i)))
        if images:
            figures = []
            for img, caption in images:
                cap = f"<figcaption>{value_html(caption)}</figcaption>" if caption else ""
                figures.append(f'<figure><img src="{img}" alt="">{cap}</figure>')
            mode = "single" if len(figures) == 1 else "multi"
            gallery = f'<div class="gallery {mode}">{"".join(figures)}</div>'

    # гимн под картинками (как в вики)
    anthem = str(d.get("anthem") or "").strip()
    anthem_dur = str(d.get("anthem_duration") or "").strip()
    anthem_html = ""
    if anthem:
        dur = esc(anthem_dur) if anthem_dur else "0:00"
        anthem_html = (
            '<div class="anthem-block">'
            f'<div class="anthem-title">{value_html(anthem)}</div>'
            '<div class="anthem-player">'
            '<span class="anthem-play" aria-hidden="true"></span>'
            f'<span class="anthem-time">{dur}</span>'
            '</div></div>'
        )

    # карты территорий
    map_imgs = []
    for i, path in enumerate(map_images(d)):
        uri = image_uri(path, work_dir)
        if uri:
            cap = map_image_caption(d, path)
            # map captions are explicit only; do not inherit the main image caption
            map_imgs.append((uri, cap))
    map_html = ""
    if map_imgs:
        figs = []
        for img, caption in map_imgs:
            cap = f"<figcaption>{value_html(caption)}</figcaption>" if caption else ""
            figs.append(f'<figure><img src="{img}" alt="">{cap}</figure>')
        mode = "single" if len(figs) == 1 else "multi"
        map_html = f'<div class="gallery map {mode}">{"".join(figs)}</div>'

    subtitle_html = f'<div class="subtitle">{value_html(subtitle)}</div>' if subtitle else ""
    kind_label = resolve_kind_label(tpl, d)
    if theme.key in {"light", "dark"} and not str(d.get("card_type_label") or "").strip():
        kind_label = ""
    kind_html = f'<div class="kind">{esc(kind_label)}</div>' if kind_label else ""
    desc_html = ""
    if description:
        desc_html = (
            '<section class="description"><h2>Описание</h2>'
            f'<div class="description-text">{value_html(description)}</div></section>'
        )

    body = body + custom_fields(d) + custom_sections(d) + desc_html
    body = stripe_rows(body)
    vars_ = theme.css_vars()
    extra_font_css = font_css_for_family(font_key, work_dir, user_id)
    fam = css_family_name(font_key)
    if fam:
        # override theme fonts
        vars_ = vars_ + f"--font:'{fam}',sans-serif;--heading-font:'{fam}',serif;"
    footer = '<div class="footer">INFOBOX BOT</div>' if watermark else ""

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; font-src data:; style-src 'unsafe-inline'">
<style>
{font_css()}
{extra_font_css}

:root {{{vars_}}}
* {{ box-sizing: border-box; box-shadow: none !important; text-shadow: none !important; }}
html, body {{ margin: 0; padding: 0; background: var(--background); color: var(--text); }}
body {{ padding: 12px; font-family: var(--font); font-size: 16px; line-height: 1.45; }}
.sheet {{
  position: relative; width: 360px; overflow: hidden; margin: 0 auto;
  background: var(--panel); border: var(--border-width) solid var(--border);
  border-radius: 0;
}}
header {{ padding: 8px 10px 6px; text-align: center; background: var(--panel); border-bottom: 0; }}
.kind {{ margin-bottom: 2px; color: var(--text-secondary); font-size: 11px; font-weight: 700; letter-spacing: .04em; text-transform: none; }}
h1 {{ margin: 0; overflow-wrap: anywhere; font: 700 23px/1.2 var(--heading-font); color: var(--text); }}
.subtitle {{ margin-top: 4px; color: var(--text); font-size: 13px; line-height: 1.35; }}
a, .wiki-link {{ color: var(--link); text-decoration: none; }}
a:hover, .wiki-link:hover {{ text-decoration: underline; }}
.gallery {{ margin: 6px 8px 8px; text-align: center; }}
.gallery.multi {{ display: flex; flex-direction: column; align-items: center; gap: 7px; }}
figure {{ min-width: 0; margin: 0; text-align: center; }}
figure img {{
  display: block; width: auto; max-width: 300px; max-height: 360px; margin: 0 auto; object-fit: contain;
  background: transparent; border: 0; border-radius: 0;
}}
.gallery.multi img {{ width: auto; height: auto; max-width: 300px; max-height: 300px; }}
figcaption {{ max-width: 320px; margin: 0 auto; padding: 4px 4px 0; text-align: center; color: var(--text); font-size: 12px; line-height: 1.3; }}
section {{ margin: 0; border-top: 0; }}
section h2 {{
  margin: 0; padding: 4px 6px; overflow-wrap: anywhere; text-align: center;
  background: var(--section-bg); color: var(--section-text);
  font: 700 14px/1.3 var(--font); letter-spacing: 0;
}}
.row {{ display: grid; grid-template-columns: minmax(0, 38%) minmax(0, 62%); border-top: 0; }}
.label, .value {{ padding: 3px 5px; min-width: 0; overflow-wrap: anywhere; }}
.label {{ color: var(--text); font-weight: 700; background: transparent; border-right: 0; }}
.value {{ color: var(--text); background: transparent; }}
.row-alt .label, .row-alt .value {{ background: transparent; }}
.sheet[data-theme="aurelia"] section > .row.row-alt .label,
.sheet[data-theme="aurelia"] section > .row.row-alt .value {{ background: var(--row-alt); }}
.side-grid {{ display: grid; grid-template-columns: 1fr 1fr; }}
.side-col {{ min-width: 0; padding: 5px 6px; overflow-wrap: anywhere; }}
.side-col + .side-col {{ border-left: var(--border-width) solid var(--border); }}
.side-item + .side-item {{ margin-top: 6px; padding-top: 0; border-top: 0; }}
.side-label {{ margin-bottom: 1px; color: var(--text); font-size: 12px; font-weight: 700; text-transform: none; letter-spacing: 0; }}
.battle-table {{ display: grid; grid-template-columns: 1fr 1fr; }}
.battle-cell {{ min-width: 0; padding: 5px 6px; overflow-wrap: anywhere; text-align: left; font-size: 13px; }}
.battle-cell + .battle-cell {{ border-left: var(--border-width) solid var(--border); }}
.battle-side-name {{
  display: flex; flex-direction: column; align-items: stretch; justify-content: flex-start;
  gap: 4px; text-align: left; font-weight: 400; font-size: 13px; min-height: 0;
}}
.battle-side-mirror {{ align-items: stretch; text-align: left; }}
.side-row, .side-row-mirror {{
  display: flex; flex-direction: row; align-items: center; gap: 5px;
  text-align: left; justify-content: flex-start;
}}
.side-row-mirror .battle-text {{ text-align: left; }}
.mini-flag {{ width: 26px; height: auto; max-height: 18px; object-fit: contain; flex: 0 0 auto; border: 1px solid var(--image-border); background: transparent; }}
.battle-text {{ min-width: 0; text-align: left; }}
.description-text {{ padding: 6px 7px 8px; overflow-wrap: anywhere; font-size: 14px; }}
.footer {{ padding: 5px 7px; text-align: right; color: var(--text-secondary); background: var(--panel); border-top: 0; font-size: 9px; letter-spacing: .02em; }}

.anthem-block {{ margin: 3px 8px 8px; text-align: center; }}
.anthem-title {{ color: var(--link); font-size: 12px; margin-bottom: 4px; }}
.anthem-player {{
  display: flex; align-items: center; justify-content: space-between;
  background: #72777d; border: 1px solid #a2a9b1;
  border-radius: 2px; padding: 0 7px; height: 28px;
  max-width: 300px; margin: 0 auto; box-sizing: border-box;
}}
.anthem-play {{
  width: 0; height: 0; flex: 0 0 auto; border-style: solid;
  border-width: 6px 0 6px 10px; border-color: transparent transparent transparent #ffffff;
  background: transparent; border-radius: 0; margin-left: 2px;
}}
.anthem-time {{
  font-size: 10px; line-height: 1; color: #ffffff; background: #202122; border-radius: 2px;
  padding: 4px 6px; flex: 0 0 auto; font-variant-numeric: tabular-nums;
}}
.gallery.map {{ margin-top: 4px; }}
.parliament-block {{ padding: 6px 8px 8px; text-align: center; }}
.parliament-title {{ margin-bottom: 4px; font-size: 13px; font-weight: 700; color: var(--text); }}
.parliament-svg {{ display: block; width: 100%; max-width: 300px; height: auto; margin: 0 auto; }}
.parliament-meta {{ margin-top: 2px; font-size: 12px; color: var(--text); }}
.parliament-legend {{ margin-top: 6px; display: flex; flex-direction: column; gap: 4px; }}
.parliament-legend-row {{ display: grid; grid-template-columns: 12px 18px minmax(0,1fr) auto; gap: 6px; align-items: center; text-align: left; }}
.party-swatch {{ width: 12px; height: 12px; border: 1px solid var(--border); display: inline-block; }}
.party-logo {{ width: 18px; height: 18px; object-fit: contain; display: inline-block; }}
.party-logo-empty {{ border: 1px dashed var(--border); background: transparent; }}
.party-name {{ min-width: 0; overflow-wrap: anywhere; font-size: 12px; }}
.party-seats {{ font-size: 11px; color: var(--text-secondary); white-space: nowrap; }}
.parliament-bottom {{ margin-top: 8px; display: flex; flex-direction: column; align-items: center; gap: 4px; }}
.parliament-flag {{ display: block; max-width: 84px; max-height: 50px; width: auto; height: auto; border: 1px solid var(--image-border); }}
.parliament-country {{ font-size: 12px; font-weight: 700; color: var(--text); }}
.parliament-note {{ margin-top: 5px; font-size: 11px; color: var(--text-secondary); }}
</style>
</head>
<body>
<article class="sheet" id="infobox" data-theme="{esc(theme.key)}">
  <header>{kind_html}<h1>{esc(title)}</h1>{subtitle_html}</header>
  {gallery}
  {anthem_html}
  {map_html}
  {body}
  {footer}
</article>
</body>
</html>"""


async def render_page(
    page: Page,
    work_dir: str | Path = ".",
    quality: str = "high",
    output: str | Path | None = None,
    watermark: bool = True,
    font_key: str = "default",
    user_id: int | None = None,
) -> Path:
    root = Path(work_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if output:
        raw_path = Path(output)
        path = raw_path.resolve() if raw_path.is_absolute() else (root / raw_path).resolve()
    else:
        path = root / f"preview_{uuid4().hex}.png"
    if path.parent != root:
        raise ValueError("PNG можно сохранять только в рабочую директорию бота.")

    scale = QUALITY_SCALE.get(quality, QUALITY_SCALE["high"])
    if page.data is None:
        page.data = {}
    page.data["_font_key"] = font_key or "default"
    page.data["_font_user_id"] = user_id

    if page.theme == "olddoc":
        from olddoc import render_olddoc

        await asyncio.to_thread(render_olddoc, page, root, quality, path, watermark)
        return path

    if page.type in ("news", "superevent", "parliament", "chart", "comparison", "election", "timeline", "composition"):
        from pillow_renderer import render_pillow

        await asyncio.to_thread(render_pillow, page, root, quality, path, watermark)
        return path

    # миротворец: своя вёрстка; Chromium или Pillow-карточка (не вики)
    if page.type == "mirotorets" or page.theme == "mirotorets":
        page.theme = "mirotorets"
        watermark = False
        try:
            from playwright.async_api import async_playwright

            async with _render_slots, async_playwright() as p:
                browser = await p.chromium.launch(
                    args=["--disable-dev-shm-usage", "--no-sandbox"],
                )
                try:
                    markup = make_mirotorets_html(page, get_theme("mirotorets"), root, watermark=False)
                    ctx = await browser.new_context(
                        viewport={"width": 820, "height": 1000},
                        device_scale_factor=scale,
                        service_workers="block",
                    )
                    tab = await ctx.new_page()
                    await tab.set_content(markup, wait_until="load")
                    await tab.evaluate("document.fonts.ready")
                    await tab.wait_for_function("Array.from(document.images).every(x => x.complete)")
                    card = tab.locator("#infobox")
                    await card.screenshot(path=str(path), type="png", animations="disabled")
                    await ctx.close()
                finally:
                    await browser.close()
            return path
        except Exception as chromium_error:
            log.warning("Миротворец: Chromium недоступен, Pillow: %s", chromium_error)
            from pillow_renderer import render_pillow

            await asyncio.to_thread(render_pillow, page, root, quality, path, False)
            return path

    try:
        from playwright.async_api import async_playwright

        async with _render_slots, async_playwright() as p:
            browser = await p.chromium.launch(
                args=["--disable-dev-shm-usage", "--no-sandbox"],
            )
            try:
                markup = make_html(page, get_theme(page.theme), root, watermark, font_key=font_key, user_id=user_id)
                ctx = await browser.new_context(
                    viewport={"width": 880, "height": 900},
                    device_scale_factor=scale,
                    service_workers="block",
                )
                tab = await ctx.new_page()
                await tab.set_content(markup, wait_until="load")
                await tab.evaluate("document.fonts.ready")
                await tab.wait_for_function("Array.from(document.images).every(x => x.complete)")
                card = tab.locator("#infobox")
                await card.screenshot(path=str(path), type="png", animations="disabled")
                await ctx.close()
            finally:
                await browser.close()
    except Exception as chromium_error:
        log.warning("Chromium renderer недоступен, использую Pillow: %s", chromium_error)
        try:
            from pillow_renderer import render_pillow

            await asyncio.to_thread(render_pillow, page, root, quality, path, watermark)
        except Exception as pillow_error:
            a = " ".join(str(chromium_error).split())[:180]
            b = " ".join(str(pillow_error).split())[:180]
            raise RuntimeError(
                f"Не сработали оба renderer. Chromium: {type(chromium_error).__name__}: {a}; "
                f"Pillow: {type(pillow_error).__name__}: {b}"
            ) from pillow_error

    return path


def render_error_text(e: Exception) -> str:
    s = " ".join(str(e).split())
    if not s:
        s = type(e).__name__
    return s[:350]
