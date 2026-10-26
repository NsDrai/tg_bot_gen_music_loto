from __future__ import annotations

import pytest

from music_lotto.parsing import clean_label, dedupe_key, find_song_index, parse_song_list


def test_parse_numbered_list():
    raw = "\n".join(
        [
            "1. Моргенштерн - кадилак",
            "2) IOWA – 140",
            "- Кино - Звезда по имени Солнце",
            "3. Моргенштерн - кадилак",
            "",
            "   ",
        ]
    )

    songs, duplicates = parse_song_list(raw)

    assert songs == [
        "Моргенштерн — кадилак",
        "IOWA — 140",
        "Кино — Звезда по имени Солнце",
    ]
    assert duplicates == 1


def test_parse_plain_list_and_digits_only_song():
    songs, duplicates = parse_song_list("140\nIOWA - 140\n\nABC\n")

    assert songs == ["140", "IOWA — 140", "ABC"]
    assert duplicates == 0


def test_parse_keeps_hyphenated_words():
    songs, _ = parse_song_list("Рок-н-ролл\nДДТ - Что такое осень")

    assert songs == ["Рок-н-ролл", "ДДТ — Что такое осень"]


def test_clean_label_removes_numbering_but_keeps_years():
    assert clean_label("12. Земфира - 1999") == "Земфира — 1999"
    assert clean_label("  •  Сплин - Выхода нет ") == "Сплин — Выхода нет"


def test_dedupe_key_ignores_case_and_dash_style():
    assert dedupe_key("Кино — Звезда") == dedupe_key("кино - звезда")
    assert dedupe_key("Ёлка - Прованс") == dedupe_key("елка — прованс")


def test_find_song_by_exact_and_partial_name():
    songs = [
        "Моргенштерн — кадилак",
        "IOWA — 140",
        "Кино — Звезда по имени Солнце",
    ]

    assert find_song_index("IOWA - 140", songs) == (2, [])
    assert find_song_index("звезда по имени солнце", songs) == (3, [])
    assert find_song_index("140", songs) == (2, [])


def test_find_song_ambiguous_and_missing():
    songs = ["Кино — Звезда", "Кино — Группа крови"]

    index, candidates = find_song_index("Кино", songs)
    assert index is None
    assert candidates == [1, 2]

    assert find_song_index("Ария", songs) == (None, [])


def test_parse_skips_headers_and_separators():
    songs, _ = parse_song_list("Список песен:\n---\nКино - Перемен\nПлейлист\n")

    assert songs == ["Кино — Перемен"]


def test_parse_rejects_too_long_line():
    with pytest.raises(ValueError):
        parse_song_list("x" * 400)
