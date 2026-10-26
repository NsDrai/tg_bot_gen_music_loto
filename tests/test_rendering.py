from __future__ import annotations

import io
import random

import pytest

from music_lotto.generator import build_cards
from music_lotto.rendering import RenderError, render_card, render_card_text

PIL = pytest.importorskip("PIL")


def make_songs(count: int) -> list[str]:
    return [f"Артист {i} — Песня номер {i}" for i in range(1, count + 1)]


@pytest.mark.parametrize("size", [6, 7])
def test_render_card_png(size):
    songs = make_songs(size * size + 10)
    cards = build_cards(len(songs), size, 3, size + 2, rng=random.Random(4))

    try:
        payload = render_card(cards[0], songs)
    except RenderError as exc:  # нет шрифта с кириллицей
        pytest.skip(str(exc))

    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(payload) > 5_000

    image = PIL.Image.open(io.BytesIO(payload))
    assert image.width == 1600
    assert image.height > 1000


def test_text_fallback_contains_songs():
    songs = make_songs(50)
    card = build_cards(50, 6, 1, 10, rng=random.Random(2))[0]

    text = render_card_text(card, songs)

    assert "Таблица 1" in text
    assert "6×6" in text
    for row in card.grid:
        for index in row:
            assert songs[index - 1][:17] in text
