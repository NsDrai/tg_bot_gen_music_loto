from __future__ import annotations

import random

import bot as bot_module
from bot import (
    count_prompt,
    first_win_prompt,
    key_text,
    parse_size_text,
    plural_ru,
    split_message,
)
from music_lotto.generator import build_cards


def make_songs(count: int) -> list[str]:
    return [f"Артист {i} — Песня {i}" for i in range(1, count + 1)]


def test_parse_size_text():
    assert parse_size_text("6") == 6
    assert parse_size_text("6x6") == 6
    assert parse_size_text("6×6") == 6
    assert parse_size_text("6 х 6") == 6
    assert parse_size_text("7*7") == 7
    assert parse_size_text("семь на семь") is None


def test_split_message_keeps_chunks_under_limit():
    lines = [f"строка {i} " + "x" * 80 for i in range(100)]
    text = "\n".join(lines)

    chunks = split_message(text, limit=500)

    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert "\n".join(chunks) == text


def test_key_mentions_every_card_and_song():
    songs = make_songs(50)
    cards = build_cards(50, 6, 5, 20, rng=random.Random(8))

    text = key_text(cards, songs, 20)

    assert "Ключ ведущего" in text
    for card in cards:
        assert f"таблица {card.number}" in text
        assert songs[card.win_song_index - 1] in text
    assert "№24" in text  # последняя победная песня: 20 + 5 - 1


def test_prompts_contain_ranges():
    songs = make_songs(50)

    count = count_prompt(6, len(songs))
    assert "от 1 до 39" in count

    prompt = first_win_prompt(songs, 6, 10, duplicates=2)
    assert "от <b>6</b> до <b>35</b>" in prompt
    assert "дубликатов: 2" in prompt


def test_first_win_prompt_with_single_option():
    prompt = first_win_prompt(make_songs(36), 6, 25, duplicates=0)

    assert "только на песню №<b>6</b>" in prompt


def test_plural_ru():
    assert plural_ru(1, "таблица", "таблицы", "таблиц") == "таблица"
    assert plural_ru(2, "таблица", "таблицы", "таблиц") == "таблицы"
    assert plural_ru(4, "таблица", "таблицы", "таблиц") == "таблицы"
    assert plural_ru(5, "таблица", "таблицы", "таблиц") == "таблиц"
    assert plural_ru(11, "таблица", "таблицы", "таблиц") == "таблиц"
    assert plural_ru(21, "таблица", "таблицы", "таблиц") == "таблица"


def test_read_env_token(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# комментарий\nOTHER=1\nBOT_TOKEN = \"123:abc\"\n", encoding="utf-8"
    )

    assert bot_module._read_env_token(env_file) == "123:abc"
    assert bot_module._read_env_token(tmp_path / "missing.env") == ""


def test_find_token_priority(monkeypatch, tmp_path):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    env_file = tmp_path / ".env"
    token_file = tmp_path / "token.txt"
    monkeypatch.setattr(bot_module, "ENV_FILE", env_file)
    monkeypatch.setattr(bot_module, "TOKEN_FILES", (token_file,))

    assert bot_module.find_token() == ("", "")

    token_file.write_text("222:bbb\n", encoding="utf-8")
    assert bot_module.find_token() == ("222:bbb", str(token_file))

    env_file.write_text("BOT_TOKEN=111:aaa\n", encoding="utf-8")
    assert bot_module.find_token() == ("111:aaa", str(env_file))

    monkeypatch.setenv("BOT_TOKEN", "333:ccc")
    assert bot_module.find_token() == ("333:ccc", "переменная окружения BOT_TOKEN")


def test_save_token_writes_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(bot_module, "ENV_FILE", env_file)

    bot_module.save_token("123:abc")

    assert bot_module._read_env_token(env_file) == "123:abc"
