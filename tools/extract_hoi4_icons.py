"""Export every ideology and available focus from the owner's two PSD files."""

import io
import json
from pathlib import Path
import sys
import zipfile

from psd_tools import PSDImage


def child(group, name):
    return next(layer for layer in group if layer.name == name)


def extract(root, output):
    existing_path = output / "catalog.json"
    previous = {e["id"]: e for e in json.loads(existing_path.read_text())} if existing_path.exists() else {}
    entries = []
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output / "icons.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        def add(layer, style, role, category, label=None):
            image = layer.topil().convert("RGBA")
            bounds = image.getchannel("A").getbbox()
            if not bounds:
                return
            image = image.crop(bounds)
            key = f"{style}_{role}_{sum(e['style'] == style and e['role'] == role for e in entries):03d}"
            old = previous.get(key)
            if old and old["source_layer"] == layer.name:
                label, category = old["label"], old["category"]
            stream = io.BytesIO()
            image.save(stream, "PNG", optimize=True)
            archive.writestr(key + ".png", stream.getvalue())
            entries.append(dict(id=key, style=style, role=role, category=category,
                                label=(label or layer.name).strip(), source_layer=layer.name,
                                width=image.width, height=image.height))

        tno = PSDImage.open(root / "tno_template_ru_v1.3.psd")
        state = child(tno, "государство")
        ideologies = child(child(state, "государства, флаг и идеологии"), "идеологии")
        for category in ideologies:
            if category.kind == "smartobject":
                add(category, "tno", "ideology", "Общие")
            elif category.is_group():
                for layer in category.descendants():
                    if layer.kind == "smartobject":
                        add(layer, "tno", "ideology", category.name)
        add(child(child(state, "партия, лидер и фокус"), "национальный фокус не выбран"),
            "tno", "focus", "Фокусы", "Фокус не выбран")

        tfr = PSDImage.open(root / "tfr_superevent_template2.psd")
        info = child(tfr, "Infobar")
        for layer in child(info, "Ideologies"):
            if layer.kind == "smartobject":
                add(layer, "tfr", "ideology", "Идеологии TFR")
        add(child(child(info, "Text"), "SOV_new_russian_era"),
            "tfr", "focus", "Фокусы", "Новая российская эра")
    (output / "catalog.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
    return entries


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "assets" / "hoi4" / "icons"
    entries = extract(Path(sys.argv[1]), out)
    for style in ("tno", "tfr"):
        for role in ("ideology", "focus"):
            print(style, role, sum(e["style"] == style and e["role"] == role for e in entries))
