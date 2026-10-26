"""Shared input and layout limits for the fixed-size TNO newspaper."""

# key: (label, characters, box, preferred font size, smallest readable font size)
NEWS_FIELDS = {
    "newspaper_name": ("Название газеты", 40, (99, 22, 571, 79), 34, 16),
    "news_title": ("Заголовок газеты", 60, (37, 103, 584, 143), 23, 14),
    "news_body": ("Текст газеты", 400, (237, 161, 578, 580), 20, 16),
    "news_date": ("Дата газеты", 30, (241, 581, 578, 618), 16, 12),
    "news_button": ("Подпись газеты", 40, (242, 622, 583, 666), 18, 12),
}


def news_prompt(page_type, key, value=""):
    if page_type != "superevent" or key not in NEWS_FIELDS:
        return ""
    _, limit, *_ = NEWS_FIELDS[key]
    return f'\n\nСимволов: {len(str(value or ""))}/{limit}, включая пробелы и переносы строк'


def news_field_error(page_type, key, value):
    if page_type != "superevent" or key not in NEWS_FIELDS or not value:
        return None
    label, limit, box, size, minimum = NEWS_FIELDS[key]
    count = len(value)
    if count > limit:
        return f"{label}: {count}/{limit} символов. Убери еще {count-limit}. Пробелы и переносы строк тоже считаются"
    # Character counts alone cannot detect an excessive number of empty lines.
    from hoi4_renderer import font, wrap

    width, height = box[2] - box[0], box[3] - box[1]
    for px in range(size, minimum - 1, -1):
        face = font("tno", px, "news")
        a, d = face.getmetrics()
        if len(wrap(value, face, width)) * (a + d + max(2, px // 6)) <= height:
            return None
    return f"{label}: {count}/{limit} символов, но строки не помещаются в окно. Убери лишние переносы или сократи текст"


def news_data_error(page_type, data):
    for key in NEWS_FIELDS:
        error = news_field_error(page_type, key, str(data.get(key) or ""))
        if error:
            return error
    return None
