# Свои шрифты (необязательно)

Бот сам находит системный шрифт с кириллицей (Arial, DejaVu Sans, Liberation Sans).
Если хочется свой шрифт, положите сюда два файла:

- `bold.ttf` — заголовки;
- `regular.ttf` — текст в клетках.

Либо укажите пути через переменные окружения:

```
LOTTO_FONT_BOLD=/path/to/font-bold.ttf
LOTTO_FONT_REGULAR=/path/to/font-regular.ttf
```

Файлы шрифтов не коммитятся в git (см. `.gitignore`).
