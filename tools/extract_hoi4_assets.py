"""Export PSD plates, exact image masks and foreground layers separately.

Development only: python tools/extract_hoi4_assets.py /path/to/upload
The source layer coordinates and opacities are preserved. No sample photos,
replacement gradients or hand-drawn frame replicas are included.
"""

from pathlib import Path
import shutil
import sys

from PIL import Image, ImageChops, ImageDraw
from psd_tools import PSDImage

OUT = Path(__file__).resolve().parents[1] / "assets" / "hoi4"


def child(group, name):
    return next(l for l in group if l.name == name)


def raster(layer, viewport):
    canvas = Image.new("RGBA", (viewport[2] - viewport[0], viewport[3] - viewport[1]))
    im = layer.topil().convert("RGBA")
    if layer.opacity != 255:
        im.putalpha(im.getchannel("A").point(lambda a: round(a * layer.opacity / 255)))
    canvas.paste(im, (layer.left - viewport[0], layer.top - viewport[1]))
    return canvas


def save(im, name):
    dest = OUT / (name + ".png")
    temporary = dest.with_suffix(".tmp")
    im.save(temporary, format="PNG", optimize=True)
    temporary.replace(dest)


def composite(group, viewport, exclude=()):
    im = group.composite(
        layer_filter=lambda l: l.visible and l.kind != "type" and l.name not in exclude,
        force=True,
    )
    canvas = Image.new("RGBA", (viewport[2] - viewport[0], viewport[3] - viewport[1]))
    canvas.paste(im, (group.left - viewport[0], group.top - viewport[1]))
    return canvas


def rectangle_mask(size, box):
    mask = Image.new("L", size)
    ImageDraw.Draw(mask).rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=255)
    return mask


def punch(plate, mask):
    plate.putalpha(ImageChops.multiply(plate.getchannel("A"), ImageChops.invert(mask)))


def main(root):
    OUT.mkdir(parents=True, exist_ok=True)
    tno = PSDImage.open(root / "tno_template_ru_v1.3.psd")
    state = child(tno, "государство")
    view = (0, 0, 863, 391)
    flag = child(child(state, "государства, флаг и идеологии"), "флаг")
    flag_mask = raster(child(flag, "бокс флага"), view).getchannel("A")
    plate = composite(
        state,
        view,
        ("флаг", "национальный фокус не выбран", "диаграмма", "идеологии", "альянсы"),
    )
    portrait_mask = rectangle_mask(plate.size, (16, 124, 201, 376))
    punch(plate, ImageChops.lighter(flag_mask, portrait_mask))
    save(plate, "tno_state_front")
    save(flag_mask, "tno_flag_mask")
    glass = Image.new("RGBA", plate.size)
    for name in ("шумы", "тени", "блик"):
        overlay = raster(child(flag, name), view)
        overlay.putalpha(ImageChops.multiply(overlay.getchannel("A"), flag_mask))
        glass = Image.alpha_composite(glass, overlay)
    save(glass, "tno_flag_glass")
    chart = child(state, "диаграмма")
    save(raster(child(chart, "диаграмма"), view), "tno_chart_front")

    event = child(tno, "супер ивент")
    view = (868, 99, 1917, 1003)
    picture = child(event, "изображение")
    mask = raster(child(picture, "бокс изображения"), view).getchannel("A")
    button_names = (
        "обычная кнопка",
        "большая кнопка",
        "кнопка побольше",
        "мега кнопка",
    )
    plate = composite(event, view, ("изображение", *button_names))
    punch(plate, mask)
    save(plate, "tno_event_front")
    save(mask, "tno_event_mask")
    effects = Image.new("RGBA", plate.size)
    for name in ("шумы", "синий", "тени"):
        overlay = raster(child(picture, name), view)
        overlay.putalpha(ImageChops.multiply(overlay.getchannel("A"), mask))
        effects = Image.alpha_composite(effects, overlay)
    save(effects, "tno_event_effects")
    for key, name in zip(("normal", "large", "wide", "full"), button_names):
        save(raster(child(event, name), view), "tno_button_" + key)

    news = child(tno, "газета")
    view = (244, 397, 862, 1080)
    picture = child(news, "изображение")
    mask = raster(child(picture, "бокс изображения"), view).getchannel("A")
    plate = composite(news, view, ("изображение", "заголовок"))
    punch(plate, mask)
    save(plate, "tno_news_front")
    save(mask, "tno_news_mask")
    effects = raster(child(picture, "тени"), view)
    effects.putalpha(ImageChops.multiply(effects.getchannel("A"), mask))
    save(effects, "tno_news_effects")
    save(raster(child(child(news, "заголовок"), "общий"), view), "tno_news_masthead")

    tfr = PSDImage.open(root / "tfr_superevent_template2.psd")
    info = child(tfr, "Infobar")
    view = (0, 0, 470, 252)
    plate = raster(child(info, "Base"), view)
    for box in ((29, 12, 96, 54), (13, 105, 118, 246)):
        punch(plate, rectangle_mask(plate.size, box))
    save(plate, "tfr_state_front")
    chart = child(child(info, "Pie chart"), "pol_piechart_overlay_63x63")
    save(raster(chart, view), "tfr_chart_front")
    event = child(tfr, "Superevent")
    view = (477, 187, 1002, 561)
    # The actual frame has partial alpha: it is designed to sit ON the photo.
    save(raster(child(event, "Super_event_bg"), view), "tfr_event_front")
    save(
        raster(child(event, "superevent picture"), view).getchannel("A"),
        "tfr_event_mask",
    )
    for src, dst in [
        ("Aldrich.ttf", "Aldrich.ttf"),
        ("Bombardier-Regular_0.ttf", "Bombardier.ttf"),
        ("a_OldTyperNr Regular.ttf", "OldTyper.ttf"),
    ]:
        shutil.copyfile(root / src, OUT / dst)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
