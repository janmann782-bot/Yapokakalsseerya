"""Extract original artwork once; psd-tools is a development dependency only.

Usage: python tools/extract_hoi4_assets.py /path/to/upload
"""

import sys
import shutil
from pathlib import Path
from psd_tools import PSDImage
from PIL import Image

OUT = Path(__file__).resolve().parents[1] / "assets" / "hoi4"


def export(layer, name, box=None, exclude=()):
    def keep(l):
        return l.visible and l.kind != "type" and l.name not in exclude

    im = layer.composite(layer_filter=keep, force=True)
    if box:
        # Composite is cropped to the group's own bounding box.
        canvas = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]))
        canvas.paste(im, (layer.left - box[0], layer.top - box[1]))
        im = canvas
    im.save(OUT / (name + ".png"), optimize=True)


def main(root):
    OUT.mkdir(parents=True, exist_ok=True)
    tno = PSDImage.open(root / "tno_template_ru_v1.3.psd")
    state = next(l for l in tno if l.name == "государство")
    export(
        state,
        "tno_state",
        (0, 0, 863, 391),
        ("национальный фокус не выбран", "диаграмма", "идеологии", "альянсы"),
    )
    event = next(l for l in tno if l.name == "супер ивент")
    export(event, "tno_event", (868, 99, 1917, 1003), ("шумы", "синий", "тени"))
    export(
        next(l for l in tno if l.name == "газета"),
        "tno_news",
        (244, 397, 862, 1080),
        ("Черно-белое", "тени"),
    )
    tfr = PSDImage.open(root / "tfr_superevent_template2.psd")
    info = next(l for l in tfr if l.name == "Infobar")
    export(next(l for l in info if l.name == "Base"), "tfr_state", (0, 0, 470, 252))
    export(
        next(l for l in tfr if l.name == "Superevent"),
        "tfr_event",
        (477, 187, 1002, 561),
        ("superevent picture",),
    )
    for src, dst in [
        ("Aldrich.ttf", "Aldrich.ttf"),
        ("Bombardier-Regular_0.ttf", "Bombardier.ttf"),
        ("a_OldTyperNr Regular.ttf", "OldTyper.ttf"),
    ]:
        shutil.copyfile(root / src, OUT / dst)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
