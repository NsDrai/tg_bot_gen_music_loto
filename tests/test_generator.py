from __future__ import annotations

import random

import pytest

from music_lotto.generator import (
    LottoError,
    build_cards,
    iter_winning_lines,
    line_song_indices,
    max_tables,
    simulate_schedule,
    validate_params,
    win_range,
)


def make_songs(count: int) -> list[str]:
    return [f"Артист {i} — Песня {i}" for i in range(1, count + 1)]


def assert_card_follows_rules(card, song_count: int) -> None:
    size = card.size
    values = [value for row in card.grid for value in row]

    assert len(values) == size * size
    assert len(set(values)) == size * size, "в таблице не должно быть повторов"
    assert all(1 <= value <= song_count for value in values)

    win_line = line_song_indices(card, card.win_kind, card.win_line_index)
    assert card.win_song_index in win_line
    assert all(value <= card.win_song_index for value in win_line)
    assert win_line.count(card.win_song_index) == 1

    # Каждая невыигрышная линия обязана содержать песню, которая прозвучит
    # позже победной: иначе линия собралась бы раньше или одновременно.
    for kind, index in iter_winning_lines(card):
        if kind == card.win_kind and index == card.win_line_index:
            continue
        line = line_song_indices(card, kind, index)
        assert any(value > card.win_song_index for value in line), (
            f"линия {kind} {index} собралась бы слишком рано"
        )


CASES = [
    (36, 6, 1, 6),
    (36, 6, 1, 30),
    (36, 6, 25, 6),
    (49, 7, 1, 7),
    (49, 7, 1, 42),
    (49, 7, 36, 7),
    (50, 6, 10, 6),
    (50, 6, 10, 35),
    (50, 7, 5, 12),
    (60, 7, 12, 30),
    (80, 6, 20, 50),
    (100, 7, 30, 60),
]


@pytest.mark.parametrize("song_count,size,count,first_win", CASES)
def test_generated_schedule_is_exact(song_count, size, count, first_win):
    for seed in range(15):
        cards = build_cards(
            song_count, size, count, first_win, rng=random.Random(seed)
        )
        assert len(cards) == count
        assert [card.number for card in cards] == list(range(1, count + 1))
        assert [card.win_song_index for card in cards] == list(
            range(first_win, first_win + count)
        )

        for card in cards:
            assert_card_follows_rules(card, song_count)

        schedule = simulate_schedule(cards, song_count)
        expected = [
            [turn - first_win + 1]
            if first_win <= turn < first_win + count
            else []
            for turn in range(1, song_count + 1)
        ]
        assert schedule == expected

        assert all(not event for event in schedule[: first_win - 1])
        assert all(not event for event in schedule[first_win - 1 + count :])


def test_cards_differ():
    cards = build_cards(50, 6, 8, 10, rng=random.Random(1))
    grids = {card.grid for card in cards}
    assert len(grids) == len(cards)


@pytest.mark.parametrize(
    "song_count,size,count,first_win",
    [
        (35, 6, 1, 6),  # мало песен для 6×6
        (48, 7, 1, 7),  # мало песен для 7×7
        (50, 6, 40, 6),  # слишком много таблиц
        (50, 6, 0, 6),  # ноль таблиц
        (50, 6, 10, 5),  # первый билет слишком рано
        (50, 6, 10, 36),  # первый билет слишком поздно
        (49, 7, 5, 39),  # первому билету не хватает песен после
    ],
)
def test_invalid_params_raise(song_count, size, count, first_win):
    with pytest.raises(LottoError):
        build_cards(song_count, size, count, first_win)


def test_limits_helpers():
    assert max_tables(50, 6) == 39
    assert max_tables(49, 7) == 36
    assert max_tables(36, 6) == 25
    assert win_range(50, 6, 10) == (6, 35)
    assert win_range(49, 7, 5) == (7, 38)
    assert validate_params(50, 6, 10, 20) == (6, 35)


def test_generator_stays_inside_limits():
    with pytest.raises(LottoError):
        validate_params(50, 6, 10, 36)
    with pytest.raises(LottoError):
        validate_params(50, 6, 10, 5)
