"""Отрисовка таблиц музыкального лото в PNG."""

from __future__ import annotations

import io
import os
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

from .generator import Card

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

FONT_ENV = {
    "bold": "LOTTO_FONT_BOLD",
    "regular": "LOTTO_FONT_REGULAR",
}

FONT_CANDIDATES = {
    "bold": [
        ASSETS_DIR / "bold.ttf",
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf"),
        Path("C:/Windows/Fonts/tahomabd.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        Path("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ],
    "regular": [
        ASSETS_DIR / "regular.ttf",
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/tahoma.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ],
}

PAGE_WIDTH = 1600
PADDING = 56
GAP = 12
HEADER_HEIGHT = 120
MAX_LINES = 4

COLOR_PAGE = "#f8fafc"
COLOR_TEXT = "#0f172a"
COLOR_MUTED = "#64748b"
COLOR_ACCENT = "#2563eb"
COLOR_ACCENT_SOFT = "#dbeafe"
COLOR_ACCENT_TEXT = "#1d4ed8"
COLOR_CELL = "#ffffff"
COLOR_CELL_ALT = "#edf3ff"
COLOR_CELL_BORDER = "#d6e0ee"
COLOR_DIVIDER = "#e2e8f0"


class RenderError(RuntimeError):
    """Не удалось найти шрифт для отрисовки карточек."""


def _font_path(kind: str) -> Path | None:
    env_name = FONT_ENV[kind]
    env_value = os.getenv(env_name)
    if env_value:
        path = Path(env_value).expanduser()
        if path.is_file():
            return path

    for candidate in FONT_CANDIDATES[kind]:
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=None)
def _font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    path = _font_path(kind)
    if path is None:
        raise RenderError(
            "Не найден шрифт с кириллицей. Положите bold.ttf и regular.ttf в "
            "assets/fonts или задайте LOTTO_FONT_BOLD / LOTTO_FONT_REGULAR."
        )
    return ImageFont.truetype(str(path), size=size)


def _split_long_word(draw: ImageDraw.ImageDraw, word: str, font, max_width: int) -> list[str]:
    parts: list[str] = []
    current = ""
    for char in word:
        candidate = current + char
        if current and draw.textlength(candidate, font=font) > max_width:
            parts.append(current)
            current = char
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = ""
    for word in words:
        pieces = (
            _split_long_word(draw, word, font, max_width)
            if draw.textlength(word, font=font) > max_width
            else [word]
        )
        for piece in pieces:
            candidate = f"{current} {piece}".strip()
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = piece
    if current:
        lines.append(current)
    return lines


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    shortened = text
    while shortened and draw.textlength(shortened + "…", font=font) > max_width:
        shortened = shortened[:-1]
    return shortened.rstrip() + "…"


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    *,
    base_size: int,
    min_size: int = 13,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    for size in range(base_size, min_size - 1, -1):
        font = _font("regular", size)
        lines = _wrap(draw, text, font, max_width)
        line_height = int(size * 1.18)
        if len(lines) <= MAX_LINES and line_height * len(lines) <= max_height:
            return font, lines, line_height

    font = _font("regular", min_size)
    lines = _wrap(draw, text, font, max_width)
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]
        lines[-1] = _ellipsize(draw, lines[-1], font, max_width)
    return font, lines, int(min_size * 1.18)


def _draw_header(draw: ImageDraw.ImageDraw, card: Card, size: int, width: int) -> None:
    title_font = _font("bold", 56)
    subtitle_font = _font("regular", 23)
    chip_font = _font("bold", 40)

    draw.rounded_rectangle(
        [PADDING, PADDING + 4, PADDING + 9, PADDING + 92],
        radius=5,
        fill=COLOR_ACCENT,
    )
    draw.text(
        (PADDING + 28, PADDING - 2),
        f"ТАБЛИЦА {card.number:02d}",
        font=title_font,
        fill=COLOR_TEXT,
    )
    draw.text(
        (PADDING + 30, PADDING + 68),
        "музыкальное лото",
        font=subtitle_font,
        fill=COLOR_MUTED,
    )

    chip_text = f"{size}×{size}"
    text_width = draw.textlength(chip_text, font=chip_font)
    chip_width = int(text_width) + 56
    chip_height = 72
    chip_x = width - PADDING - chip_width
    chip_y = PADDING + 12

    draw.rounded_rectangle(
        [chip_x, chip_y, chip_x + chip_width, chip_y + chip_height],
        radius=20,
        fill=COLOR_ACCENT_SOFT,
    )
    draw.text(
        (chip_x + chip_width / 2, chip_y + chip_height / 2),
        chip_text,
        font=chip_font,
        fill=COLOR_ACCENT_TEXT,
        anchor="mm",
    )


def render_card(card: Card, songs: Sequence[str], *, width: int = PAGE_WIDTH) -> bytes:
    """Рисует одну таблицу и возвращает PNG в виде байтов."""

    size = card.size
    cell_width = (width - 2 * PADDING - GAP * (size - 1)) // size
    cell_height = int(cell_width * 0.72)
    grid_top = PADDING + HEADER_HEIGHT
    grid_height = size * cell_height + GAP * (size - 1)
    footer_top = grid_top + grid_height + 28
    height = footer_top + 30 + PADDING

    image = Image.new("RGB", (width, height), COLOR_PAGE)
    draw = ImageDraw.Draw(image)

    _draw_header(draw, card, size, width)

    base_font_size = max(22, int(cell_width * 0.145))

    for row in range(size):
        for col in range(size):
            x = PADDING + col * (cell_width + GAP)
            y = grid_top + row * (cell_height + GAP)

            draw.rounded_rectangle(
                [x, y, x + cell_width, y + cell_height],
                radius=14,
                fill=COLOR_CELL_ALT if (row + col) % 2 else COLOR_CELL,
                outline=COLOR_CELL_BORDER,
                width=2,
            )

            label = songs[card.grid[row][col] - 1]
            font, lines, line_height = _fit_text(
                draw,
                label,
                cell_width - 26,
                cell_height - 18,
                base_size=base_font_size,
            )
            draw.multiline_text(
                (x + cell_width / 2, y + cell_height / 2),
                "\n".join(lines),
                font=font,
                fill=COLOR_TEXT,
                anchor="mm",
                align="center",
                spacing=max(2, line_height // 6),
            )

    draw.line(
        [(PADDING, footer_top - 14), (width - PADDING, footer_top - 14)],
        fill=COLOR_DIVIDER,
        width=2,
    )
    draw.text(
        (width / 2, footer_top + 2),
        "Песни звучат в порядке списка",
        font=_font("regular", 22),
        fill=COLOR_MUTED,
        anchor="ma",
    )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_card_text(card: Card, songs: Sequence[str], *, column_width: int = 18) -> str:
    """Текстовая копия таблицы — запасной вариант, если нет шрифтов."""

    def cut(value: str) -> str:
        if len(value) <= column_width:
            return value.ljust(column_width)
        return (value[: column_width - 1] + "…").ljust(column_width)

    border = "+" + "+".join("-" * column_width for _ in range(card.size)) + "+"
    lines = [f"Таблица {card.number} · {card.size}×{card.size}", border]
    for row in card.grid:
        lines.append("|" + "|".join(cut(songs[index - 1]) for index in row) + "|")
        lines.append(border)
    return "\n".join(lines)
