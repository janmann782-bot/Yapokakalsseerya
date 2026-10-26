"""Field validation shared by wizard, draft editor, saved cards and paste input."""
from hoi4_limits import news_data_error, news_field_error, news_prompt


def field_error(page_type, key, value):
    if page_type == "stamp":
        from stamp_renderer import stamp_field_error
        return stamp_field_error(page_type, key, value)
    return news_field_error(page_type, key, value)


def data_error(page_type, data):
    if page_type == "stamp":
        from stamp_renderer import LIMITS
        for key in (*LIMITS, "stamp_color", "stamp_shape", "stamp_texture", "stamp_wear", "stamp_rings", "stamp_width", "stamp_separator", "stamp_angle", "stamp_logo_mode", "stamp_weight", "stamp_border_style"):
            error = field_error(page_type, key, data.get(key))
            if error:
                return error
        return None
    return news_data_error(page_type, data)


def field_prompt(page_type, key, value=""):
    if page_type == "stamp":
        from stamp_renderer import LIMITS
        if key in LIMITS:
            return f"\n\nСимволов: {len(str(value or ''))}/{LIMITS[key]}"
        if key == "stamp_weight":
            return "\n\nОт 400 до 900: обычный, полужирный и усиленная жирность"
        if key == "stamp_width":
            return "\n\nТолщина линий от 1 до 24"
        if key == "stamp_rings":
            return "\n\nОт 0 до 6. 0 - без рамок и колец"
        if key == "stamp_shape":
            return "\n\nКруглая, овальная или прямоугольная. По умолчанию круглая"
        if key == "stamp_wear":
            return "\n\nОт 0 до 100: 0 - четкий, 25 - легкая потертость, 50 - средняя, 100 - сильная. По умолчанию 0"
        if key == "stamp_texture":
            return "\n\nЧеткий или потертый. По умолчанию четкий"
        if key == "stamp_color":
            return "\n\nСиний, черный, красный, зеленый, фиолетовый или HEX. По умолчанию синий"
        return ""
    return news_prompt(page_type, key, value)
