"""Логика музыкального лото: разбор списка, генерация и отрисовка таблиц."""

from .generator import (
    Card,
    LottoError,
    build_cards,
    max_tables,
    simulate_schedule,
    validate_params,
    win_range,
    WIN_KINDS,
)

__all__ = [
    "Card",
    "LottoError",
    "build_cards",
    "max_tables",
    "simulate_schedule",
    "validate_params",
    "win_range",
    "WIN_KINDS",
]
