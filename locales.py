from __future__ import annotations

import html

from version import __version__

RU = {
    'welcome': (
        f'<b>InfoBox Bot</b> · {__version__}\n\n'
        'Энциклопедические карточки стран, регионов, битв и людей\n\n'
        'Выбери <b>Создать</b> или отправь данные текстом:\n'
        '<blockquote>Тип: страна\n'
        'Название: Кефирстан\n'
        'Столица: Каменный Мост</blockquote>'
    ),
    'help': (
        f'<b>Как пользоваться</b> · {__version__}\n\n'
        '1 <b>Создать</b> - тип - поля - картинка - тема - PNG\n'
        '2 Лишнее можно <b>пропустить</b>\n'
        '3 Быстрый ввод: несколько строк <code>Поле: значение</code>'
    ),
    'choose_type': (
        'Что делаем?\n'
    ),
    'field_prompt': (
        '{label}\n'
        '{hint}Шаг {step} из {total}'
    ),
    'field_hint': 'Можно написать несколько строк\n\n',
    'current_value': 'Сейчас здесь:\n<blockquote>{value}</blockquote>',
    'text_only': 'Тут нужен именно текст',
    'empty_value': 'Похоже значение пустое\nНапиши что-нибудь или вернись назад',
    'title_required': 'Без названия страницу не сохранить',
    'too_long': 'Текст получился слишком длинным\nМаксимум {limit} символов',
    'send_image': (
        'Картинки\n'
        'Что загружать: {label}\n'
        'PNG JPEG WEBP до {max_mb} МБ\n'
        'Сейчас: {count}/{max_count}\n'
        'Когда закончишь жми Готово\n'
        '(если есть картинки с территорией то они на след. Шаг)'
    ),
    'send_map_image': (
        'Карта территорий\n'
        'PNG JPEG WEBP до {max_mb} МБ\n'
        'Сейчас: {count}/{max_count}\n'
        'Кинь карту / схему территорий или жми Готово'
    ),
    'choose_theme': (
        '<b>Оформление карточки</b>\n\nВикипедия — белая карточка с черным текстом и серыми разделами\n'
    ),
    'rendering': 'Делаем твою картинку:\n{bar} {percent}%',
    'render_error': 'Не получилось собрать PNG\nВот что пошло не так: {error}',
    'draft_caption': '{title}\nТема: {theme}',
    'saved': 'Сохранил: <b>{title}</b>',
    'cancelled': 'Ок отменил',
    'draft_missing': 'Черновик уже закрыт\nЖми Создать',
    'image_saved': 'Готово\nИзображение добавлено: {count}/{max_count}',
    'image_removed': 'Изображение {number} удалено\nОсталось: {count}',
    'image_limit': 'На одну страницу помещается до {max_count} изображений',
    'image_bad': 'С этой картинкой не получилось: {error}',
    'image_only': 'Здесь жду картинку\nЛибо нажми одну из кнопок ниже',
    'image_caption_prompt': 'Как подписать изображение {number}?\nМожно отправить текст до {limit} символов',
    'image_caption_saved': 'Подпись сохранил\nМожешь отправить следующую картинку',
    'image_caption_skipped': 'Оставил картинку без подписи\nМожешь отправить следующую',
    'battle_sides_title': (
        'Редактор сторон\n'
        'Выбери сторону'
    ),
    'battle_side_name': 'Как назвать эту сторону?',
    'battle_member_name': 'Напиши название участника',
    'battle_flag_prompt': 'Пришли флаг участника или пропусти этот шаг',
    'battle_flag_only': 'Здесь нужен файл с флагом',
    'battle_side_limit': 'В одной стороне уже максимум 10 участников',
    'images_continue': 'Можешь отправить следующую картинку или нажать Готово',
    'custom_name': 'Как назовём это поле?',
    'custom_value': 'Что написать в поле {name}?',
    'custom_added': 'Готово\nПоле добавлено',
    'section_prompt': (
        'Пришли раздел одним сообщением\n'
        'В первой строке напиши название раздела\n'
        'Дальше поля в формате Поле: значение\n\n'
        'Например:\n'
        'ВОЕННЫЕ ДАННЫЕ\n'
        'Армия: 250 000\n'
        'Резерв: 600 000'
    ),
    'section_bad': 'Не смог разобрать этот раздел\nВ первой строке нужно название дальше хотя бы одно Поле: значение',
    'section_added': 'Готово\nРаздел добавлен',
    'limit_reached': 'Здесь уже достигнут лимит полей или разделов',
    'section_title_empty': 'У раздела должно быть название',
    'fields_title': (
        'Что хочешь изменить?\n'
        'Галочка у уже заполненных'
    ),
    'edit_value': (
        'Поле: {label}\n'
        'Отправь значение\n'
        'Или <code>-</code> чтобы очистить'
    ),
    'field_saved': 'Готово\nПоле обновлено',
    'quick_found': 'Кажется я всё понял\nНашёл полей: {count}\nТип страницы: {type}\n\n{summary}{extra}',
    'quick_unknown': '\n\nВот эти строки я не смог уверенно разобрать:\n{lines}',
    'quick_warnings': '\n\nИ ещё лучше проверить:\n{lines}',
    'quick_hint': 'Я не понял это сообщение\nПопробуй прислать несколько строк Поле: значение или выбери Создать',
    'pages_empty': 'Сохранённых страниц пока нет',
    'pages_title': (
        'Вот твои страницы\n'
    ),
    'page_not_found': 'Не нашёл эту страницу\nВозможно она уже удалена',
    'page_caption': '{title}\nТема: {theme}',
    'copied': 'Готово\nСделал копию: {title}',
    'delete_confirm': 'Точно удалить страницу {title}?\nВернуть её потом не получится',
    'deleted': 'Страница удалена',
    'exporting': 'Готовлю PNG',
    'settings': (
        'Твои настройки\n'
        '<u>Тема по умолчанию</u>: {theme}\n'
        '<u>Язык</u>: {language}\n'
        '<u>Качество PNG</u>: {quality}\n'
        '<u>Формат</u>: {format}\n'
        '<u>Подпись INFOBOX BOT</u>: {watermark}\n'
        '<u>Шрифт</u>: {font}'
    ),
    'settings_theme': (
        'Какую тему ставить новым страницам?\n'
    ),
    'settings_quality': (
        'Какое качество PNG?\n'
        'Чем выше - тем тяжелее файл'
    ),
    'settings_saved': 'Готово\nНастройку сохранил',
    'watermark_saved': 'Подпись INFOBOX BOT теперь {state}',
    'only_ru': 'Скоро добавим если надо',
    'only_png': 'Скоро добавим если надо',
    'unexpected_error': 'Что-то пошло не так\nПопробуй ещё раз',
    'news_later': 'Потом добавим',
    'olddoc_options': (
        'Варианты старого документа\n'
        'Сид: {seed}\n'
        'Кружки: {cups}\n'
        'Бумага: {paper}\n'
        'Текст: {text}\n'
        'Флаги: {flags}\n'
        'Под веществами: {sub}\n'
        'Окошко: {window}\n'
        'Обводка: {outline}\n\n'
        'Новый сид меняет разрывы яркость и расположение кружек'
    ),
    'olddoc_reseeded': 'Новый вариант документа готов',
    'olddoc_cups': 'Кружек: {count}',
    'olddoc_paper': 'Бумага: вариант {n}',
    'olddoc_text_normal': 'Текст: обычный',
    'olddoc_text_drunk': 'Текст: пьяный',
    'olddoc_flags_normal': 'Флаги: обычные',
    'olddoc_flags_drunk': 'Флаги: пьяные',
    'olddoc_sub_on': 'Под веществами: вкл',
    'olddoc_sub_off': 'Под веществами: выкл',
    'olddoc_window_on': 'Окошко: вкл',
    'olddoc_window_off': 'Окошко: выкл',
    'olddoc_outline_on': 'Обводка: вкл',
    'olddoc_outline_off': 'Обводка: выкл',
    'olddoc_bw_on': 'ЧБ: вкл',
    'olddoc_bw_off': 'ЧБ: выкл',
    'olddoc_applied': 'Изменения применены',
    'olddoc_pick': (
        'Варианты старого документа\n'
        'Сначала настрой кнопками потом нажми «Подтвердить изменения»\n\n'
        'Сид: {seed}\n'
        'Бумага: {paper}\n'
        'Кружки: {cups}\n'
        'Текст: {text}\n'
        'Флаги: {flags}\n'
        'Под веществами: {sub}\n'
        'Окошко: {window}\n'
        'Обводка: {outline}\n'
        'ЧБ: {bw}'
    ),
}

LOCALES = {"ru": RU}


def tr(key: str, lang: str = "ru", **kwargs) -> str:
    d = LOCALES.get(lang, RU)
    s = d.get(key, RU.get(key, key))
    safe_kwargs = {k: html.escape(str(v), quote=False) for k, v in kwargs.items()}
    return s.format(**safe_kwargs)
