"""Shared stamp options for buttons, validation and rendering."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

OPTIONS = {
    "stamp_shape": [("Круглая", "круглая"), ("Овальная", "овальная"), ("Прямоугольная", "прямоугольная")],
    "stamp_color": [("🔵 Синий", "синий"), ("⚫ Черный", "черный"), ("🔴 Красный", "красный"), ("🟢 Зеленый", "зеленый"), ("🟣 Фиолетовый", "фиолетовый")],
    "stamp_wear": [("Четкий", "0"), ("Легкие пропуски", "15"), ("Потертый", "50"), ("Сильно потертый", "100")],
    "stamp_rings": [("Одно", "1"), ("Два", "2")],
    "stamp_width": [("Тонкие", "2"), ("Средние", "5"), ("Толстые", "9")],
    "stamp_separator": [("Звезды", "звезды"), ("Точки", "точки"), ("Без разделителей", "нет")],
    "stamp_angle": [("Ровно", "0"), ("↶ -8°", "-8"), ("↷ +8°", "8")],
    "stamp_logo_mode": [("Герб вместо текста", "вместо текста"), ("Герб и текст", "с текстом")],
}
LABELS = {"stamp_shape":"Форма печати", "stamp_color":"Цвет печати", "stamp_wear":"Вид оттиска",
          "stamp_rings":"Количество рамок / колец", "stamp_width":"Толщина линий", "stamp_separator":"Разделители",
          "stamp_angle":"Наклон", "stamp_logo_mode":"Герб в центре"}
PRESETS = ["Оплачено", "Утверждено", "Копия верна", "Секретно"]


def option_kb(key, scope, base=None):
    options = OPTIONS.get(key)
    if options is None:
        return base
    buttons = [InlineKeyboardButton(text=label, callback_data=f"stamp:pick:{scope}:{key}:{i}") for i,(label,_) in enumerate(options)]
    rows = [buttons[i:i+2] for i in range(0,len(buttons),2)]
    if base:
        rows += base.inline_keyboard
    return InlineKeyboardMarkup(inline_keyboard=rows)


def number_option(key, value):
    ranges = {"stamp_rings": (1,2,2), "stamp_width": (1,16,5), "stamp_angle": (-30,30,0)}
    low,high,default = ranges[key]
    if value is None or str(value).strip() == "":
        return default
    try:
        text = str(value).strip()
        if text.lstrip("-").isascii() and text.lstrip("-").isdecimal():
            result = int(text)
            if low <= result <= high:
                return result
    except (ValueError, TypeError):
        pass
    raise ValueError(f"{LABELS[key]}: укажи целое число от {low} до {high}")


def settings_kb(scope):
    rows = [[InlineKeyboardButton(text=label,callback_data=f"stamp:option:{scope}:{key}")] for key,label in LABELS.items()]
    rows.extend([[InlineKeyboardButton(text="Готовые штампы",callback_data=f"stamp:presets:{scope}"),
                  InlineKeyboardButton(text="На документ",callback_data=f"stamp:document:{scope}")],
                 [InlineKeyboardButton(text="Назад к печати",callback_data=f"stamp:back:{scope}")]])
    return InlineKeyboardMarkup(inline_keyboard=rows)
