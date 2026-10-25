"""Country infobox order, shared by the HTML and offline PNG renderers."""
from templates import Field, Template


def country_groups(tpl: Template, data: dict) -> list[tuple[str, list[Field]]]:
    groups = [
        ("", ("official_language", "capital", "largest_city", "government", "head_of_state", "head_of_government", "parliament", "legislature_seats", "ruling_party", "ideology")),
        ("Территория", ("area", "water_percent", "highest_point", "lowest_point", "climate", "borders")),
        ("Население", ("population", "population_year", "density", "ethnic_groups", "religion", "other_languages", "life_expectancy")),
        ("История", ("founded", "independence", "constitution")),
        ("Экономика", ("gdp_nominal", "gdp_ppp", "gdp_per_capita", "gdp_growth", "inflation", "unemployment", "currency", "hdi", "gini", "exports", "imports")),
        ("Другие сведения", ("timezone", "phone_code", "internet_domain", "iso_code", "ioc_code", "driving_side", "power_voltage", "military")),
    ]
    used = {"card_type_label", "title", "official_name", "description", "image_caption", "anthem", "anthem_duration", "alt_name", "motto"}
    result = []
    for title, keys in groups:
        used.update(keys)
        fields = [f for key in keys if (f := tpl.get_field(key)) and data.get(key) not in (None, "", [])]
        if fields:
            result.append((title, fields))
    # New template fields remain visible without changing the layout module.
    remaining = [f for f in tpl.fields if f.key not in used and data.get(f.key) not in (None, "", [])]
    if remaining:
        result.append(("Дополнительные сведения", remaining))
    return result
