"""Генерация таблиц музыкального лото.

Правила, которые гарантирует генератор:

1. Песни звучат строго в том порядке, в котором они записаны в списке.
2. До песни ``first_win`` ни одна таблица не собирает ни строку, ни столбец.
3. На песне ``first_win`` выигрывает первая таблица.
4. Каждая следующая песня закрывает ровно одну следующую таблицу.
   Двух победителей в одном ходу быть не может.
5. Внутри таблицы все песни разные.

Как это устроено
----------------
У каждой таблицы есть заранее выбранная выигрышная линия (строка или столбец).
В ней лежит победная песня и ``size - 1`` песен, которые прозвучали раньше.
Во всех остальных линиях стоит «блокер» — песня, которая прозвучит позже
победной. Пока блокер не прозвучал, линия собраться не может, поэтому таблица
выигрывает ровно на своей песне. Остальные клетки заполняются случайными
песнями из списка.

Из-за блокеров у каждой таблицы должно быть не меньше ``size`` песен после
победной. Отсюда и ограничения на количество таблиц и на номер первого
победного билета (см. :func:`validate_params`).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable, Sequence

WIN_KINDS = ("row", "col")


class LottoError(ValueError):
    """Параметры игры не позволяют собрать таблицы по правилам."""


@dataclass(frozen=True)
class Card:
    """Одна таблица.

    ``grid`` хранит номера песен (с 1), а не сами названия: так генератор
    не зависит от отображения и его проще проверять.
    """

    number: int
    grid: tuple[tuple[int, ...], ...]
    win_song_index: int
    win_kind: str
    win_line_index: int

    @property
    def size(self) -> int:
        return len(self.grid)


def max_tables(song_count: int, size: int) -> int:
    """Сколько таблиц максимум можно собрать из такого списка.

    Первая таблица не может выиграть раньше ``size``-й песни, а последней нужно
    ещё ``size`` песен после победной, поэтому ``count <= song_count - 2*size + 1``.
    """

    return max(0, song_count - 2 * size + 1)


def win_range(song_count: int, size: int, count: int) -> tuple[int, int]:
    """Допустимый диапазон номера песни для первого победного билета."""

    low = size
    high = song_count - size - count + 1
    return low, high


def validate_params(song_count: int, size: int, count: int, first_win: int) -> tuple[int, int]:
    """Проверяет параметры и возвращает допустимый диапазон первого билета."""

    if size not in (6, 7):
        raise LottoError("Размер таблицы должен быть 6×6 или 7×7.")

    need = size * size
    if song_count < need:
        raise LottoError(
            f"Для таблицы {size}×{size} нужно минимум {need} уникальных песен, "
            f"а в списке {song_count}."
        )

    limit = max_tables(song_count, size)
    if count < 1:
        raise LottoError("Количество таблиц должно быть не меньше 1.")
    if count > limit:
        raise LottoError(
            f"Столько таблиц не получится: при {song_count} песнях и таблице "
            f"{size}×{size} максимум {limit}. Введите число от 1 до {limit}."
        )

    low, high = win_range(song_count, size, count)
    if not low <= first_win <= high:
        raise LottoError(
            f"Первый победный билет должен быть на песне с №{low} по №{high}. "
            f"Иначе правила игры не выполнятся."
        )

    return low, high


def build_cards(
    song_count: int,
    size: int,
    count: int,
    first_win: int,
    *,
    rng: random.Random | None = None,
    attempts: int = 8,
) -> list[Card]:
    """Собирает ``count`` таблиц и проверяет их симуляцией игры."""

    validate_params(song_count, size, count, first_win)
    rng = rng or random.Random()

    for _ in range(attempts):
        cards = _build_once(song_count, size, count, first_win, rng)
        unique_grids = len({card.grid for card in cards}) == len(cards)
        if unique_grids and verify_schedule(cards, song_count, first_win):
            return cards

    # Конструкция детерминированно удовлетворяет правилам, поэтому сюда
    # попасть можно только при ошибке в коде.
    raise RuntimeError("Не удалось собрать таблицы по правилам, попробуйте ещё раз.")


def _build_once(
    song_count: int,
    size: int,
    count: int,
    first_win: int,
    rng: random.Random,
) -> list[Card]:
    cards: list[Card] = []

    for offset in range(count):
        win_song = first_win + offset
        before = list(range(1, win_song))
        after = list(range(win_song + 1, song_count + 1))
        rng.shuffle(before)
        rng.shuffle(after)

        kind = rng.choice(WIN_KINDS)
        line_index = rng.randrange(size)
        grid = [[0] * size for _ in range(size)]

        if kind == "row":
            line_cells = [(line_index, col) for col in range(size)]
        else:
            line_cells = [(row, line_index) for row in range(size)]

        winner_slot = rng.randrange(size)
        for slot, (row, col) in enumerate(line_cells):
            grid[row][col] = win_song if slot == winner_slot else before.pop()

        blockers = [after.pop() for _ in range(size)]

        if kind == "row":
            others = [row for row in range(size) if row != line_index]
            blocker_rows = others + [rng.choice(others)]
            rng.shuffle(blocker_rows)
            for col, row in enumerate(blocker_rows):
                grid[row][col] = blockers[col]
        else:
            others = [col for col in range(size) if col != line_index]
            blocker_cols = others + [rng.choice(others)]
            rng.shuffle(blocker_cols)
            for row, col in enumerate(blocker_cols):
                grid[row][col] = blockers[row]

        used = {value for row in grid for value in row if value}
        pool = [value for value in range(1, song_count + 1) if value not in used]
        rng.shuffle(pool)
        empty = [(row, col) for row in range(size) for col in range(size) if grid[row][col] == 0]
        if len(pool) < len(empty):
            raise AssertionError("Не хватило песен для заполнения таблицы")

        for row, col in empty:
            grid[row][col] = pool.pop()

        cards.append(
            Card(
                number=offset + 1,
                grid=tuple(tuple(row) for row in grid),
                win_song_index=win_song,
                win_kind=kind,
                win_line_index=line_index + 1,
            )
        )

    return cards


def simulate_schedule(cards: Sequence[Card], song_count: int) -> list[list[int]]:
    """Проигрывает все песни и возвращает победителей на каждом ходу.

    Результат — список длиной ``song_count``; элемент с индексом ``t - 1``
    содержит номера таблиц (1-based), которые впервые собрали линию на
    песне ``t``.
    """

    if not cards:
        return [[] for _ in range(song_count)]

    size = cards[0].size
    won = [False] * len(cards)
    marked = [[[False] * size for _ in range(size)] for _ in cards]
    positions = [
        {song: (row, col) for row, line in enumerate(card.grid) for col, song in enumerate(line)}
        for card in cards
    ]
    schedule: list[list[int]] = []

    for turn in range(1, song_count + 1):
        winners: list[int] = []

        for index, card in enumerate(cards):
            if won[index]:
                continue

            position = positions[index].get(turn)
            if position is None:
                continue

            row, col = position
            marked[index][row][col] = True
            board = marked[index]

            has_row = any(all(board[r][c] for c in range(size)) for r in range(size))
            has_col = any(all(board[r][c] for r in range(size)) for c in range(size))
            if has_row or has_col:
                winners.append(index + 1)

        for number in winners:
            won[number - 1] = True

        schedule.append(winners)

    return schedule


def verify_schedule(cards: Sequence[Card], song_count: int, first_win: int) -> bool:
    """Проверяет, что таблицы выигрывают ровно в задуманном порядке."""

    expected = [
        [turn - first_win + 1] if first_win <= turn < first_win + len(cards) else []
        for turn in range(1, song_count + 1)
    ]
    return simulate_schedule(cards, song_count) == expected


def iter_winning_lines(card: Card) -> Iterable[tuple[str, int]]:
    """Все линии таблицы — удобно для проверок и тестов."""

    for row in range(card.size):
        yield "row", row + 1
    for col in range(card.size):
        yield "col", col + 1


def line_song_indices(card: Card, kind: str, line_index: int) -> list[int]:
    """Номера песен в строке (1-based) или столбце (1-based)."""

    if kind == "row":
        return list(card.grid[line_index - 1])
    if kind == "col":
        return [card.grid[row][line_index - 1] for row in range(card.size)]
    raise ValueError(f"Неизвестный тип линии: {kind}")
