Патч типографики для последней версии aoleo_mirotorets_parliament_only.

Заменить в папке бота два файла:
- renderer.py
- pillow_renderer.py

Что изменено:
- light/dark: обычный текст остаётся sans-serif;
- главный заголовок стал serif обычного веса, ближе к Wikipedia/Vector;
- при наличии Linux Libertine в системе используется он;
- fallback: Liberation Serif;
- Pillow fallback использует ту же логику;
- остальные темы не менялись.

Проверка: test_core.py — 29/29 OK.
