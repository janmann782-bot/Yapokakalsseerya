# Artwork sources

Original artwork supplied by the repository owner in this session:

- tno_template_ru_v1.3.psd (1920 x 1080)
- tfr_superevent_template2.psd (1003 x 564)
- Aldrich.ttf (Aldrich RUS by Daymarius)
- Bombardier-Regular_0.ttf
- a_OldTyperNr Regular.ttf

The PNGs contain separate foreground plates, masks and clipped effects, with
editable sample text and sample people removed. Image windows are transparent.
The TFR event uses the actual partially transparent Super_event_bg sprite.
TNO effects retain original pixel alpha and layer opacity, each applied once. Font files are copied unchanged. TFR uses the existing repository font
PixeloidSans.otf. Attribution here records provenance, not a new license grant.

To reproduce the extraction locally, install psd-tools as a development tool and
run `python tools/extract_hoi4_assets.py /path/to/original/files`.
Production uses Pillow only and does not open PSDs.

No sample portraits, faction emblems or percentage distributions are baked into
the rendered card. Images have explicit roles. Missing party shares remain
unknown. Newspaper masthead can be replaced with user text; the original
masthead remains when the field is empty.

`icons/catalog.json` and `icons/icons.zip` contain the native ideology and focus
layers from both PSD files. Hidden alternatives are exported as individual RGBA
PNGs, cropped only to their nontransparent bounds. Labels, original layer names,
style and role are retained in the catalog. There are 169 TNO ideologies and
306 TFR ideologies. Each PSD contains one focus graphic. Reproduce this export
with `python tools/extract_hoi4_icons.py /path/to/original/files`.
