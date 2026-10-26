"""Разбор списка песен и поиск песни по названию."""

from __future__ import annotations

import re
from typing import Sequence

NUMBER_PREFIX = re.compile(r"^\s*\d{1,4}\s*[.)]\s*")
BULLET_PREFIX = re.compile(r"^\s*[•·*]\s+|^\s*[-–—]\s+")
INLINE_SPACES = re.compile(r"\s+")
DASH_SEPARATOR = re.compile(r"\s+[-–—]\s+")
EN_DASH_SEPARATOR = re.compile(r"\s*[–—]\s*")

MAX_SONGS = 400
MAX_LINE_LENGTH = 300
HEADER_LINE = re.compile(
    r"^(?:список(?:\s+песен)?|плейлист|трек-?лист|музыка|песни)\s*:?$",
    flags=re.IGNORECASE,
)


def clean_label(line: str) -> str:
    """Убирает нумерацию и приводит строку к аккуратному виду."""

    value = line.strip().lstrip("\ufeff")
    value = NUMBER_PREFIX.sub("", value)
    value = BULLET_PREFIX.sub("", value)
    value = INLINE_SPACES.sub(" ", value).strip()
    value = DASH_SEPARATOR.sub(" — ", value)
    value = EN_DASH_SEPARATOR.sub(" — ", value)
    return value.strip(" \t\"'«»")


def dedupe_key(value: str) -> str:
    """Ключ для сравнения песен без учёта регистра и лишних пробелов."""

    key = value.replace("ё", "е").replace("Ё", "Е").lower()
    key = DASH_SEPARATOR.sub(" - ", key)
    key = EN_DASH_SEPARATOR.sub("-", key)
    key = re.sub(r"\s+", " ", key).strip()
    return key


def parse_song_list(raw_text: str) -> tuple[list[str], int]:
    """Возвращает список песен и количество удалённых дубликатов.

    Понимает строки вида ``1. Исполнитель - Песня``, ``1) ...``, ``- ...``
    и просто ``Исполнитель - Песня``. Порядок строк сохраняется.
    """

    songs: list[str] = []
    seen: set[str] = set()
    duplicates = 0

    for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not line.strip():
            continue
        if len(line) > MAX_LINE_LENGTH:
            raise ValueError("Слишком длинная строка в списке — проверьте, что это песня.")
        label = clean_label(line)
        if not label or not re.search(r"[^\W_]", label, flags=re.UNICODE):
            continue
        if HEADER_LINE.match(label):
            continue

        key = dedupe_key(label)
        if key in seen:
            duplicates += 1
            continue

        seen.add(key)
        songs.append(label)

    if len(songs) > MAX_SONGS:
        raise ValueError(f"Слишком много песен: максимум {MAX_SONGS}.")

    return songs, duplicates


def find_song_index(query: str, songs: Sequence[str]) -> tuple[int | None, list[int]]:
    """Ищет песню по названию.

    Возвращает ``(номер, [])`` при однозначном совпадении, ``(None, [])`` —
    если ничего не найдено, и ``(None, варианты)`` — если подходит несколько.
    """

    cleaned = clean_label(query)
    needle = dedupe_key(cleaned)
    if not needle:
        return None, []

    exact = [index for index, song in enumerate(songs, 1) if dedupe_key(song) == needle]
    if len(exact) == 1:
        return exact[0], []
    if len(exact) > 1:
        return None, exact

    partial = [
        index
        for index, song in enumerate(songs, 1)
        if needle in dedupe_key(song) or dedupe_key(song) in needle
    ]
    if len(partial) == 1:
        return partial[0], []

    return None, partial[:8]
