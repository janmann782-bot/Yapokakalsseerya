"""Procedural seals rendered locally, with a transparent PNG export."""
from __future__ import annotations

import math
import os
import random
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFont, ImageOps

from media import page_images

STAMP_LAYOUT_VERSION = 7
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
                        "прямоугольная": "rectangle", "прямоугольный": "rectangle", "прямоугольник": "rectangle", "rectangle": "rectangle", "овальная": "oval", "овал": "oval", "oval": "oval"},
        "stamp_texture": {"": "clean", "четкий": "clean", "четкая": "clean", "clean": "clean",
                          "потертый": "worn", "потертая": "worn", "worn": "worn"},
    }
    if text not in choices[key]:
        raise ValueError("Укажи форму: круглая, овальная или прямоугольная" if key == "stamp_shape" else
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


@lru_cache(maxsize=2)
def wear_source(name):
    with Image.open(ROOT / "assets" / "stamp_wear" / name) as source:
        return source.convert("L")


def wear_mask(size, level, seed):
    if not level:
        return Image.new("L",size,255)
    rng=random.Random(str(seed)+":texture-eraser-v1")
    names=["metal007.png","metal009.png"]
    scores=[]
    for _ in range(rng.choice((1,2,2))):
        source=wear_source(rng.choice(names))
        if rng.getrandbits(1):
            source=ImageOps.mirror(source)
        if rng.getrandbits(1):
            source=ImageOps.flip(source)
        # Repeating before rotation keeps all sampled pixels inside the texture.
        tiled=Image.new("L",(source.width*3,source.height*3))
        for x in range(3):
            for y in range(3):
                tiled.paste(source,(x*source.width,y*source.height))
        tiled=tiled.rotate(rng.randrange(360),resample=Image.Resampling.NEAREST)
        w,h=rng.randint(140,550),rng.randint(140,550)
        cx=tiled.width//2+rng.randint(-100,100)
        cy=tiled.height//2+rng.randint(-100,100)
        crop=tiled.crop((cx-w//2,cy-h//2,cx-w//2+w,cy-h//2+h))
        crop=crop.resize(size,Image.Resampling.NEAREST)
        if rng.getrandbits(1):
            crop=ImageOps.invert(crop)
        scores.append(ImageOps.equalize(crop))
    score=scores[0]
    for layer in scores[1:]:
        score=ImageChops.darker(score,layer)
    # Level controls erased area, not opacity. At 100 the stamp stays readable.
    target=round(size[0]*size[1]*level*.004)
    histogram=score.histogram()
    count=0
    threshold=0
    for threshold,n in enumerate(histogram):
        count+=n
        if count>=target:
            break
    return score.point([0 if value<=threshold else 255 for value in range(256)])


def hard_alpha(canvas):
    canvas.putalpha(canvas.getchannel("A").point([0 if a<128 else 255 for a in range(256)]))
    return canvas


def worn_ink(canvas, level=35, seed="180"):
    canvas=hard_alpha(canvas)
    canvas.putalpha(ImageChops.multiply(canvas.getchannel("A"),wear_mask(canvas.size,level,seed)))
    return canvas


def stamp_font_path(data, root):
    from fonts_catalog import resolve_font_files, resolve_user_font, list_bundled_families
    key = str(data.get("stamp_font") or data.get("_font_key") or "default")
    from stamp_controls import number_option
    weight = number_option("stamp_weight", data.get("stamp_weight"))
    if key == "default":
        return ROOT / ("DejaVuSans-Bold.ttf" if weight >= 600 else "DejaVuSans.ttf")
    if key.startswith("user:"):
        uid = data.get("_font_user_id")
        path = resolve_user_font(root, int(uid), key) if uid is not None else None
    elif key in {k for k, _ in list_bundled_families()}:
        regular, bold = resolve_font_files(key)
        path = (bold or regular) if weight >= 600 else regular
    else:
        path = None
    if path is None:
        raise ValueError("Шрифт недоступен. Выбери другой или загрузи его заново")
    return path



def stroke_units(data):
    from stamp_controls import number_option
    if not data.get("stamp_weight"):
        return 0
    weight = number_option("stamp_weight", data.get("stamp_weight"))
    key = str(data.get("stamp_font") or data.get("_font_key") or "default")
    # Imported fonts need synthetic weight because only one face is uploaded.
    if key.startswith("user:"):
        return (weight-400)/100
    return (weight-600)/100 if weight >= 600 else (weight-400)/100*.5


def stroke_width(size, strength):
    return math.ceil(size/66*strength) if strength else 0


def frame(draw, box, width, style="сплошная", ellipse=False, color=None):
    if style == "сплошная":
        (draw.ellipse if ellipse else draw.rectangle)(box, outline=color, width=width)
        return
    x0,y0,x1,y1=box
    inset=width/2
    x0,y0,x1,y1=x0+inset,y0+inset,x1-inset,y1-inset
    if ellipse:
        rx,ry=(x1-x0)/2,(y1-y0)/2
        cx,cy=(x0+x1)/2,(y0+y1)/2
        steps=max(100,math.ceil(math.pi*(rx+ry)))
        points=[(cx+rx*math.cos(i*2*math.pi/steps),cy+ry*math.sin(i*2*math.pi/steps)) for i in range(steps+1)]
    else:
        points=[(x0,y0),(x1,y0),(x1,y1),(x0,y1),(x0,y0)]
    # Walk the whole perimeter so spacing stays continuous through corners.
    period=max(24,width*3) if style=="пунктир" else max(12,width*2.5)
    distance=0
    next_dot=0
    for a,b in zip(points,points[1:]):
        length=math.dist(a,b)
        count=max(1,math.ceil(length/2))
        for j in range(count):
            t=j/count
            p=(a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t)
            end=((a[0]+(b[0]-a[0])*(j+1)/count),(a[1]+(b[1]-a[1])*(j+1)/count))
            current=distance+length*t
            if style=="пунктир" and current%period<period*.6:
                draw.line((p,end),fill=color,width=width)
            elif style=="точки" and current>=next_dot:
                r=width/2
                draw.ellipse((p[0]-r,p[1]-r,p[0]+r,p[1]+r),fill=color)
                next_dot=current+period
        distance+=length

def face(size, font_path=None):
    return ImageFont.truetype(str(font_path or ROOT / "DejaVuSans-Bold.ttf"), size)


def arc_font(text, font_path=None, radius=390, strength=0):
    for size in range(58, 19, -1):
        font = face(size, font_path)
        if sum(font.getlength(char) + 2 + 2*stroke_width(size,strength) for char in text) <= math.radians(140) * radius:
            return font
    raise ValueError("Надпись по кругу слишком длинная. Сократи текст")


def stamp_field_error(page_type, key, value):
    if page_type != "stamp" or not value:
        return None
    text = str(value).strip()
    if key in LIMITS and len(text) > LIMITS[key]:
        return f"Символов: {len(text)}/{LIMITS[key]}. Сократи надпись"
    try:
        from stamp_controls import number_option, OPTIONS
        if key in ("stamp_rings", "stamp_width", "stamp_angle", "stamp_weight"):
            number_option(key, value)
        if key in ("stamp_separator", "stamp_logo_mode", "stamp_border_style") and text not in {v for _,v in OPTIONS[key]}:
            raise ValueError("Выбери значение кнопкой")
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


def arc_text(canvas, text, bottom, color, font_path=None, oval=False, strength=0):
    text = " ".join(str(text or "").upper().split())
    if not text:
        return
    radius = 330 if oval else 390
    font = arc_font(text, font_path, radius, strength)
    sw = stroke_width(font.size,strength)
    advances = [font.getlength(char) + 2 + 2*sw for char in text]
    offset = -sum(advances) / 2
    ascent, descent = font.getmetrics()
    for char, advance in zip(text, advances):
        angle = (90 - math.degrees((offset + advance/2) / radius) if bottom else
                 -90 + math.degrees((offset + advance/2) / radius))
        if not char.isspace():
            bbox = font.getbbox(char, stroke_width=sw)
            glyph = Image.new("RGBA", (bbox[2]-bbox[0]+4,bbox[3]-bbox[1]+4))
            ImageDraw.Draw(glyph).text((2-bbox[0],2-bbox[1]), char, font=font, fill=color, stroke_width=sw, stroke_fill=color)
            radians = math.radians(angle)
            tangent = math.degrees(math.atan2((270 if oval else 390)*math.cos(radians), -390*math.sin(radians)))
            rotation = 180-tangent if bottom else -tangent
            glyph = glyph.rotate(rotation, Image.Resampling.NEAREST, expand=True)
            radians = math.radians(angle)
            center = (512 + 390 * math.cos(radians), (370 if oval else 512) + (270 if oval else 390) * math.sin(radians))
            canvas.alpha_composite(glyph, (round(center[0] - glyph.width/2), round(center[1] - glyph.height/2)))
        offset += advance


def center_text(canvas, text, box, color, font_path=None, max_size=66, strength=0):
    from hoi4_renderer import wrap

    if not str(text or "").strip():
        return
    text = str(text).strip().upper()
    x0, y0, x1, y1 = box
    for size in range(max_size, 19, -1):
        font = face(size, font_path)
        sw = stroke_width(size,strength)
        if any(font.getlength(word)+2*sw > x1-x0 for word in text.split()):
            continue
        lines = wrap(text, font, x1-x0-2*sw)
        boxes = [font.getbbox(line,stroke_width=sw) for line in lines]
        gap = max(6,round(size*.22))
        height = sum(b[3]-b[1] for b in boxes)+gap*(len(lines)-1)
        if height <= y1-y0 and all(b[2]-b[0] <= x1-x0 for b in boxes):
            break
    else:
        raise ValueError("Центральная надпись слишком длинная. Сократи текст")
    # Font metrics can still include empty bearing pixels. Rasterize and crop
    # the actual ink before placing the complete multiline block in its box.
    block_width=max(b[2]-b[0] for b in boxes)
    block=Image.new("RGBA",(math.ceil(block_width)+8,math.ceil(height)+8))
    draw=ImageDraw.Draw(block)
    y=4
    for line,bbox in zip(lines,boxes):
        x=4+(block_width-(bbox[2]-bbox[0]))/2
        draw.text((round(x-bbox[0]),round(y-bbox[1])),line,font=font,fill=color,
                  stroke_width=sw,stroke_fill=color)
        y+=bbox[3]-bbox[1]+gap
    bounds=block.getchannel("A").getbbox()
    if bounds:
        block=block.crop(bounds)
        canvas.alpha_composite(block,(round((x0+x1-block.width)/2),round((y0+y1-block.height)/2)))


def stamp_image(data, root):
    for key in (*LIMITS, "stamp_color", "stamp_shape", "stamp_texture", "stamp_wear", "stamp_rings", "stamp_width", "stamp_separator", "stamp_angle", "stamp_logo_mode", "stamp_weight", "stamp_border_style"):
        error = stamp_field_error("stamp", key, data.get(key))
        if error:
            raise ValueError(error)
    color = ink_color(data.get("stamp_color"))
    font_path = stamp_font_path(data, root)
    strength = stroke_units(data)
    from stamp_controls import number_option
    shape = stamp_option("stamp_shape", data.get("stamp_shape"))
    rectangular, oval = shape == "rectangle", shape == "oval"
    rings = number_option("stamp_rings", data.get("stamp_rings"))
    width = number_option("stamp_width", data.get("stamp_width"))
    style = data.get("stamp_border_style") or "сплошная"
    height = 640 if rectangular else 740 if oval else 1024
    canvas = Image.new("RGBA", (1024, height))
    draw = ImageDraw.Draw(canvas)
    if rectangular:
        spacing=max(14,width+5)
        for i in range(rings):
            inset=35+i*spacing
            frame(draw,(inset,inset,1024-inset,640-inset),width,style,color=color)
        # Keep every text area inside the innermost frame, even with six thick frames.
        content_inset=max(65,35+max(0,rings-1)*spacing+width+16) if rings else 65
        left,right=content_inset,1024-content_inset
        top,bottom=content_inset,640-content_inset
        available=bottom-top
        header_bottom=top+available*.24
        footer_top=bottom-available*.2
        if data.get("stamp_top"):
            draw.line((left,header_bottom,right,header_bottom),fill=color,width=max(1,width//2))
        if data.get("stamp_bottom"):
            draw.line((left,footer_top,right,footer_top),fill=color,width=max(1,width//2))
        center_text(canvas,data.get("stamp_top"),(left,top,right,header_bottom-8),color,font_path,strength=strength)
        center_text(canvas,data.get("stamp_bottom"),(left,footer_top+8,right,bottom),color,font_path,strength=strength)
        body_top=header_bottom+10 if data.get("stamp_top") else top
        body_bottom=footer_top-10 if data.get("stamp_bottom") else bottom
    else:
        cy = 370 if oval else 512
        inner_rx,inner_ry=335,(213 if oval else 335)
        if rings:
            frame(draw,(52,cy-(320 if oval else 460),972,cy+(320 if oval else 460)),width,style,ellipse=True,color=color)
        for i in range(max(0,rings-1)):
            # Extra rings grow inward, leaving a clear band for the curved text.
            inner_rx=335-i*max(14,width+5)
            inner_ry=(213 if oval else 335)-i*max(14,width+5)
            frame(draw,(512-inner_rx,cy-inner_ry,512+inner_rx,cy+inner_ry),width,style,ellipse=True,color=color)
        separator = data.get("stamp_separator") or "звезды"
        for x in (122, 902):
            if separator == "точки":
                draw.ellipse((x-7,cy-7,x+7,cy+7), fill=color)
            elif separator == "звезды":
                points = [(x + (15 if i % 2 == 0 else 6) * math.cos(-math.pi/2 + i*math.pi/5),
                           cy + (15 if i % 2 == 0 else 6) * math.sin(-math.pi/2 + i*math.pi/5)) for i in range(10)]
                draw.polygon(points, fill=color)
        arc_text(canvas, data.get("stamp_top"), False, color, font_path, oval, strength)
        arc_text(canvas, data.get("stamp_bottom"), True, color, font_path, oval, strength)
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
                logo_only = data.get("stamp_logo_mode") == "вместо текста"
                logo_size = (250 if rectangular else 330 if oval else 440) if logo_only else (150 if rectangular else 190 if oval else 270)
                if rectangular:
                    logo_size = min(logo_size, int((body_bottom-body_top)*(1 if logo_only else .52)), right-left)
                elif rings>2:
                    logo_size=min(logo_size,int((min(inner_rx,inner_ry)-width)*1.2*(1 if logo_only else .425)))
                logo = ImageOps.contain(logo.crop(bounds), (logo_size, logo_size), Image.Resampling.NEAREST)
                logo_top = (220 if rectangular else 205 if oval else 292) if logo_only else (215 if rectangular else 200 if oval else 300)
                if rectangular:
                    logo_top = round((body_top+body_bottom-logo_size)/2) if logo_only else round(body_top)
                elif rings>2:
                    logo_top=round(cy-logo_size/2) if logo_only else round(cy-(inner_ry-width)*.60)
                canvas.alpha_composite(logo, ((1024-logo.width)//2, logo_top + (logo_size-logo.height)//2))
                has_logo = True
    box = (290, 600, 734, 730) if has_logo else (280, 342, 744, 682)
    if rectangular:
        box = (left,body_top+(body_bottom-body_top)*.56,right,body_bottom) if has_logo else (left,body_top,right,body_bottom)
    if oval:
        box = (290, 410, 734, 530) if has_logo else (280, 255, 744, 485)
    if not rectangular and rings>2:
        half_x=min(232,int((inner_rx-width)*.73))
        half_y=min(170 if not oval else 115,int((inner_ry-width)*.60))
        box=(512-half_x,cy if has_logo else cy-half_y,512+half_x,cy+half_y)
    plain_rect = rectangular and not data.get("stamp_top") and not data.get("stamp_bottom") and not has_logo
    if plain_rect:
        box = (left,top,right,bottom)
    if not (has_logo and data.get("stamp_logo_mode") == "вместо текста"):
        center_text(canvas, data.get("stamp_center"), box, color, font_path, 120 if plain_rect else 66, strength)
    level = wear_level(data)
    canvas = worn_ink(canvas, level, data.get("stamp_seed", "180"))
    angle = number_option("stamp_angle", data.get("stamp_angle"))
    return canvas.rotate(angle, resample=Image.Resampling.NEAREST, expand=True) if angle else canvas


def render_stamp(page, root, output, quality="high"):
    page.data.setdefault("stamp_seed", uuid4().hex)
    result = stamp_image(page.data, root)
    size = {"standard": 768, "high": 1024, "ultra": 2048}.get(quality, 1024)
    if size != 1024:
        result = result.resize((size, round(size * result.height / result.width)), Image.Resampling.NEAREST)
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
