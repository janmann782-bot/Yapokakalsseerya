from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Theme:
    key: str
    name: str
    background: str
    panel: str
    panel_alt: str
    text: str
    text_secondary: str
    accent: str
    border: str
    section_bg: str
    section_text: str
    link: str
    font: str
    heading_font: str
    border_width: int = 1
    radius: int = 4
    pixel_border: bool = False
    image_border: str = "#A2A9B1"
    row_alt: str | None = None

    def css_vars(self) -> str:
        d = {
            "background": self.background,
            "panel": self.panel,
            "panel-alt": self.panel_alt,
            "text": self.text,
            "text-secondary": self.text_secondary,
            "accent": self.accent,
            "border": self.border,
            "section-bg": self.section_bg,
            "section-text": self.section_text,
            "link": self.link,
            "font": self.font,
            "heading-font": self.heading_font,
            "border-width": f"{self.border_width}px",
            "radius": f"{self.radius}px",
            "image-border": self.image_border,
            "row-alt": self.row_alt or self.panel,
            "pixel-step": "3px" if self.pixel_border else "0px",
        }
        return ";".join(f"--{k}:{v}" for k, v in d.items())


LIGHT = Theme(
    key="light",
    name="Светлая",
    background="#ffffff",
    panel="#f8f9fa",
    panel_alt="#f8f9fa",
    text="#202122",
    text_secondary="#54595d",
    accent="#3366cc",
    border="#a2a9b1",
    section_bg="#eaecf0",
    section_text="#202122",
    link="#3366cc",
    font="'Wikipedia Sans', 'Liberation Sans', Arial, Helvetica, sans-serif",
    heading_font="'Wikipedia Serif', 'Liberation Serif', Georgia, 'Times New Roman', serif",
    radius=0,
)


DARK = Theme(
    key="dark",
    name="Темная",
    background="#101418",
    panel="#202122",
    panel_alt="#202122",
    text="#eaecf0",
    text_secondary="#c8ccd1",
    accent="#88a3e8",
    border="#54595d",
    section_bg="#27292d",
    section_text="#eaecf0",
    link="#88a3e8",
    font="'Wikipedia Sans', 'Liberation Sans', Arial, Helvetica, sans-serif",
    heading_font="'Wikipedia Serif', 'Liberation Serif', Georgia, 'Times New Roman', serif",
    radius=0,
    image_border="#72777d",
)


AURELIA = Theme(
    key="aurelia",
    name="Aurelia",
    background="#000000",
    panel="#000000",
    panel_alt="#000000",
    text="#a9f38f",
    text_secondary="#a9f38f",
    accent="#a9f38f",
    border="#a9f38f",
    section_bg="#000000",
    section_text="#a9f38f",
    link="#a9f38f",
    font="'Isaac Fill', 'InfoBox Mono', monospace",
    heading_font="'Isaac Fill', 'InfoBox Mono', monospace",
    border_width=3,
    radius=0,
    pixel_border=False,
    image_border="#a9f38f",
)


OLDDOC = Theme(
    key="olddoc",
    name="Старый документ",
    background="#3a342c",
    panel="#e8dcc0",
    panel_alt="#dfd0ae",
    text="#2c2418",
    text_secondary="#5a4e3a",
    accent="#6b5a3e",
    border="#8a7a5c",
    section_bg="#d4c4a0",
    section_text="#2c2418",
    link="#4a3c28",
    font="'Times New Roman', 'Liberation Serif', 'Wikipedia Serif', serif",
    heading_font="'Times New Roman', 'Liberation Serif', 'Wikipedia Serif', serif",
    border_width=1,
    radius=0,
    pixel_border=False,
    image_border="#8a7a5c",
)


FIRE_RISES = Theme(
    key="fire_rises",
    name="THE FIRE RISES",
    background="#000000",
    panel="#f0eef5",
    panel_alt="#e8e6ed",
    text="#1a1a1a",
    text_secondary="#4a4a4a",
    accent="#7b5ea7",
    border="#6b4f8a",
    section_bg="#2d1f3d",
    section_text="#e8e0f0",
    link="#7b5ea7",
    font="'Pixeloid Sans', monospace",
    heading_font="'Pixeloid Sans', monospace",
    border_width=1,
    radius=0,
    pixel_border=False,
    image_border="#6b6b6b",
)


MIROTORETS = Theme(
    key="mirotorets",
    name="Миротворец",
    background="#ffffff",
    panel="#ffffff",
    panel_alt="#f5f5f5",
    text="#1a1a1a",
    text_secondary="#555555",
    accent="#0066cc",
    border="#cccccc",
    section_bg="#e8f0fe",
    section_text="#1a1a1a",
    link="#0066cc",
    font="'DejaVu Sans', Arial, Helvetica, sans-serif",
    heading_font="'DejaVu Sans', Arial, Helvetica, sans-serif",
    border_width=1,
    radius=4,
    pixel_border=False,
    image_border="#cccccc",
)


THEMES = {x.key: x for x in (LIGHT, DARK, AURELIA, OLDDOC, FIRE_RISES, MIROTORETS)}

# Theme available only for these page types (missing key = all types)
THEME_PAGE_TYPES: dict[str, set[str] | None] = {
    "olddoc": {"country", "region", "battle", "person"},
    "fire_rises": {"news", "superevent"},
    "mirotorets": {"mirotorets"},
    # ordinary themes not for news/superevent/mirotorets
    "light": {"country", "region", "battle", "person"},
    "dark": {"country", "region", "battle", "person"},
    "aurelia": {"country", "region", "battle", "person"},
}


def theme_allowed(theme_key: str, page_type: str) -> bool:
    allowed = THEME_PAGE_TYPES.get(theme_key)
    if allowed is None:
        return True
    return page_type in allowed


def get_theme(key: str) -> Theme:
    return THEMES.get(key, LIGHT)
