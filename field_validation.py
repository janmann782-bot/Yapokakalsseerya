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
        for key in (*LIMITS, "stamp_color"):
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
        if key == "stamp_color":
            return "\n\nСиний, черный, красный, зеленый, фиолетовый или HEX. По умолчанию синий"
        return ""
    return news_prompt(page_type, key, value)
