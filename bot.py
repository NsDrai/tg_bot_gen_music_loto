"""Телеграм-бот «Музыкальное лото».

Запуск:
    python bot.py
Токен берётся из переменной окружения BOT_TOKEN, из файла .env рядом с ботом
или из встроенного token.txt (см. сборку exe). Если токена нет, бот спросит
его в консоли и сохранит в .env.
"""

from __future__ import annotations

import asyncio
import html
import io
import logging
import os
import re
import sys
from pathlib import Path
from typing import Sequence

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

try:  # python-dotenv не обязателен, но с ним удобнее
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from music_lotto.generator import (
    LottoError,
    build_cards,
    max_tables,
    validate_params,
    win_range,
)
from music_lotto.parsing import find_song_index, parse_song_list
from music_lotto.rendering import RenderError, render_card, render_card_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("music-lotto")

router = Router()

MIN_SONGS = 36
SEND_DELAY = 0.35
MESSAGE_LIMIT = 3800

APP_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
ENV_FILE = APP_DIR / ".env"
TOKEN_FILES = (APP_DIR / "token.txt", BUNDLE_DIR / "token.txt")

_busy_chats: set[int] = set()


def _read_env_token(path: Path) -> str:
    """Достаёт BOT_TOKEN из простого .env, не требуя python-dotenv."""

    try:
        content = path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "BOT_TOKEN":
            return value.strip().strip("\"'")
    return ""


def find_token() -> tuple[str, str]:
    """Ищет токен и возвращает его вместе с описанием источника."""

    env_token = (os.getenv("BOT_TOKEN") or "").strip()
    if env_token:
        return env_token, "переменная окружения BOT_TOKEN"

    if ENV_FILE.is_file():
        token = _read_env_token(ENV_FILE)
        if token:
            return token, str(ENV_FILE)

    for path in TOKEN_FILES:
        if not path.is_file():
            continue
        try:
            token = path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            continue
        if token:
            return token, str(path)

    return "", ""


def save_token(token: str) -> None:
    """Сохраняет токен в .env рядом с ботом, чтобы не спрашивать снова."""

    try:
        ENV_FILE.write_text(f"BOT_TOKEN={token}\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Не удалось сохранить .env: %s", exc)
        return
    logger.info("Токен сохранён в %s", ENV_FILE)


def load_token() -> str:
    """Возвращает токен, при необходимости спрашивая его в консоли."""

    token, source = find_token()
    if token:
        logger.info("Токен найден: %s", source)
        return token

    message = (
        "Токен бота не найден.\n\n"
        "1. Откройте @BotFather в Telegram.\n"
        "2. Отправьте /newbot или /token и скопируйте токен.\n"
        "3. Вставьте его сюда и нажмите Enter.\n"
        "Токен сохранится рядом с ботом в файле .env.\n"
    )
    print(message)

    if not sys.stdin or not sys.stdin.isatty():
        raise SystemExit(
            "Токен не задан. Создайте .env с строкой BOT_TOKEN=... рядом с ботом."
        )

    try:
        token = input("BOT_TOKEN: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit("Ввод токена прерван.") from None

    if not token:
        raise SystemExit("Пустой токен. Запустите бота заново и вставьте токен.")

    save_token(token)
    return token


class Flow(StatesGroup):
    songs = State()
    size = State()
    count = State()
    first_win = State()
    ready = State()


WELCOME_TEXT = (
    "🎶 <b>Музыкальное лото</b>\n\n"
    "Собираю таблицы так, чтобы игра была честной:\n"
    "• песни звучат строго в порядке списка;\n"
    "• до первого победного билета ни одна таблица не собирает линию;\n"
    "• после него каждый следующий трек закрывает ровно одну таблицу — "
    "двойных побед не бывает.\n\n"
    "<b>Шаг 1 из 4.</b> Пришлите список песен — по одной в строке:\n\n"
    "<code>1. Моргенштерн - кадилак\n"
    "2. IOWA - 140\n"
    "3. ...</code>\n\n"
    "Можно отправить <code>.txt</code> файлом. Минимум 36 песен, для 7×7 — 49."
)

HELP_TEXT = (
    "<b>Как это работает</b>\n\n"
    "1️⃣ Присылаете список песен — по одной в строке. Нумерация и маркеры "
    "списка не важны.\n"
    "2️⃣ Выбираете размер таблицы: 6×6 или 7×7.\n"
    "3️⃣ Указываете, сколько таблиц нужно.\n"
    "4️⃣ Указываете песню, на которой должна выиграть первая таблица.\n\n"
    "Дальше бот присылает таблицы и отдельный <b>ключ ведущего</b>: в нём "
    "видно, какая таблица и на какой песне выигрывает.\n\n"
    "<b>Правила, которые соблюдает бот</b>\n"
    "• Все песни звучат в порядке списка.\n"
    "• Победный билет — это таблица, где полностью собралась строка или столбец.\n"
    "• До выбранной песни ни у одной таблицы нет собранной линии.\n"
    "• На выбранной песне выигрывает первая таблица, на каждой следующей — "
    "ровно одна следующая. Два билета в один ход выиграть не могут.\n\n"
    "<b>Почему есть ограничения</b>\n"
    "Каждой таблице нужен запас песен после победной, иначе её линии "
    "соберутся слишком рано. Поэтому номер первого победного билета и "
    "количество таблиц ограничены — бот подсказывает допустимый диапазон.\n\n"
    "Команды: /start — новая игра, /cancel — сбросить ввод."
)


def esc(value: str) -> str:
    return html.escape(value, quote=False)


def plural_ru(number: int, one: str, few: str, many: str) -> str:
    """Русская форма слова для числа: 1 таблица, 2 таблицы, 5 таблиц."""

    number = abs(number) % 100
    if 11 <= number <= 19:
        return many
    number %= 10
    if number == 1:
        return one
    if 2 <= number <= 4:
        return few
    return many


def parse_size_text(text: str) -> int | None:
    cleaned = (
        text.lower()
        .replace("х", "x")
        .replace("×", "x")
        .replace("*", "x")
        .replace(" ", "")
    )
    return {"6": 6, "6x6": 6, "7": 7, "7x7": 7}.get(cleaned)


def size_keyboard(song_count: int) -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    if song_count >= 36:
        row.append(InlineKeyboardButton(text="6×6 · 36 песен", callback_data="size:6"))
    if song_count >= 49:
        row.append(InlineKeyboardButton(text="7×7 · 49 песен", callback_data="size:7"))
    return InlineKeyboardMarkup(inline_keyboard=[row] if row else [])


def result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔁 Другой вариант", callback_data="more:regen"),
                InlineKeyboardButton(text="🎯 Другая песня", callback_data="more:win"),
            ],
            [
                InlineKeyboardButton(text="📐 Другой размер", callback_data="more:size"),
                InlineKeyboardButton(text="🆕 Новый список", callback_data="more:new"),
            ],
        ]
    )


def first_win_prompt(songs: Sequence[str], size: int, count: int, duplicates: int) -> str:
    low, high = win_range(len(songs), size, count)
    if low == high:
        parts = [
            "<b>Шаг 4 из 4.</b> На какой песне должна выиграть первая таблица?",
            "",
            f"При этих параметрах первый билет может выпасть только на песню "
            f"№<b>{low}</b> — «{esc(songs[low - 1])}».",
            "",
            f"Введите <code>{low}</code> или название песни.",
        ]
    else:
        parts = [
            "<b>Шаг 4 из 4.</b> На какой песне должна выиграть первая таблица?",
            "",
            f"Введите название песни или её номер — от <b>{low}</b> до <b>{high}</b>.",
            "",
            f"Раньше песни №{low} линия собраться не может, а позже №{high} "
            "не хватит песен, чтобы остальные таблицы выигрывали по очереди.",
            "",
            f"Например: <code>{low}</code> — «{esc(songs[low - 1])}»",
            f"Максимум: <code>{high}</code> — «{esc(songs[high - 1])}»",
        ]
    if duplicates:
        parts += [
            "",
            f"⚠️ Из списка убрано дубликатов: {duplicates}. Нумерация идёт "
            "по очищенному списку.",
        ]
    return "\n".join(parts)


def count_prompt(size: int, song_count: int) -> str:
    limit = max_tables(song_count, size)
    return (
        f"<b>Шаг 3 из 4.</b> Сколько таблиц {size}×{size} сделать?\n\n"
        f"Введите число от 1 до {limit}.\n\n"
        "Таблицы будут выигрывать по очереди: первая — на выбранной вами песне, "
        "каждая следующая — на следующем треке."
    )


def key_text(cards, songs: Sequence[str], first_win: int) -> str:
    last_song = first_win + len(cards) - 1
    lines = [
        "🔑 <b>Ключ ведущего</b> — не показывайте игрокам",
        "",
        f"До песни №{first_win} ни одна таблица не собирает линию. "
        "Песни включаются строго по порядку списка.\n"
        "Строки считаются сверху, столбцы — слева.",
        "",
    ]
    for card in cards:
        song = songs[card.win_song_index - 1]
        kind = "строка" if card.win_kind == "row" else "столбец"
        lines.append(f"<b>№{card.win_song_index}</b> · «{esc(song)}»")
        lines.append(
            f"　→ выигрывает <b>таблица {card.number}</b> ({kind} {card.win_line_index})"
        )
    lines += [
        "",
        f"Игра заканчивается на песне №{last_song}: к этому моменту закрыты "
        f"все таблицы ({len(cards)}).",
    ]
    return "\n".join(lines)


def split_message(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


async def delete_sent(bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    chat_id = data.get("chat_id")
    message_ids = data.get("sent_ids") or []
    if not chat_id:
        return
    for message_id in message_ids:
        try:
            await bot.delete_message(chat_id, message_id)
        except TelegramAPIError:
            pass
    await state.update_data(sent_ids=[])


async def send_photo(bot: Bot, chat_id: int, payload: bytes, filename: str, caption: str):
    file = BufferedInputFile(payload, filename=filename)
    for attempt in range(3):
        try:
            return await bot.send_photo(chat_id, file, caption=caption)
        except TelegramRetryAfter as exc:
            logger.warning("Лимит Telegram, ждём %s секунд", exc.retry_after)
            await asyncio.sleep(exc.retry_after + 1)
        except TelegramAPIError:
            if attempt == 2:
                raise
            await asyncio.sleep(1.5)
    return None


async def deliver_cards(
    bot: Bot,
    state: FSMContext,
    chat_id: int,
    cards,
    songs: Sequence[str],
    first_win: int,
) -> None:
    size = len(cards[0].grid)
    sent_ids: list[int] = []

    try:
        intro = await bot.send_message(
            chat_id,
            f"🎲 Готово: <b>{len(cards)}</b> "
            f"{plural_ru(len(cards), 'таблица', 'таблицы', 'таблиц')} {size}×{size}.\n"
            f"Первый победный билет — песня <b>№{first_win}</b> "
            f"«{esc(songs[first_win - 1])}».\n\n"
            "Сейчас пришлю таблицы и ключ ведущего.",
        )
        sent_ids.append(intro.message_id)

        text_mode = False
        payloads: list[bytes] = []
        try:
            for card in cards:
                payloads.append(render_card(card, songs))
        except Exception as exc:  # RenderError или неожиданная ошибка Pillow
            logger.warning("Не удалось отрисовать таблицы, перехожу к тексту: %s", exc)
            text_mode = True

        if text_mode:
            document = "\n\n".join(render_card_text(card, songs) for card in cards)
            sent = await bot.send_document(
                chat_id,
                BufferedInputFile(
                    document.encode("utf-8"),
                    filename=f"music-lotto-{size}x{size}.txt",
                ),
                caption="Таблицы в текстовом виде (не нашлись шрифты для картинок).",
            )
            sent_ids.append(sent.message_id)
        else:
            for card, payload in zip(cards, payloads):
                message = await send_photo(
                    bot,
                    chat_id,
                    payload,
                    f"table-{card.number:02d}.png",
                    f"Таблица {card.number} из {len(cards)} · {size}×{size}",
                )
                if message:
                    sent_ids.append(message.message_id)
                await asyncio.sleep(SEND_DELAY)

        chunks = split_message(key_text(cards, songs, first_win))
        for index, chunk in enumerate(chunks):
            is_last = index == len(chunks) - 1
            message = await bot.send_message(
                chat_id,
                chunk,
                reply_markup=result_keyboard() if is_last else None,
            )
            sent_ids.append(message.message_id)
    finally:
        await state.update_data(chat_id=chat_id, sent_ids=sent_ids)


async def generate_and_send(bot: Bot, state: FSMContext, chat_id: int) -> None:
    if chat_id in _busy_chats:
        return

    data = await state.get_data()
    songs = data.get("songs") or []
    size = data.get("size")
    count = data.get("count")
    first_win = data.get("first_win")

    if not songs or not size or not count or not first_win:
        await bot.send_message(chat_id, "Данные потерялись. Начните заново: /start")
        await state.clear()
        return

    _busy_chats.add(chat_id)
    try:
        await delete_sent(bot, state)
        try:
            validate_params(len(songs), size, count, first_win)
            cards = build_cards(len(songs), size, count, first_win)
        except (LottoError, RuntimeError) as exc:
            await bot.send_message(chat_id, f"Не получилось собрать таблицы: {exc}")
            return

        await state.set_state(Flow.ready)
        try:
            await deliver_cards(bot, state, chat_id, cards, songs, first_win)
        except Exception:
            logger.exception("Ошибка при отправке таблиц")
            await bot.send_message(
                chat_id,
                "Не удалось отправить таблицы. Попробуйте ещё раз:",
                reply_markup=result_keyboard(),
            )
    finally:
        _busy_chats.discard(chat_id)


async def accept_song_list(message: Message, state: FSMContext, raw_text: str) -> None:
    try:
        songs, duplicates = parse_song_list(raw_text)
    except ValueError as exc:
        await message.answer(f"Не смог разобрать список: {exc}")
        return

    if not songs:
        await message.answer(
            "В этом тексте не нашлось песен. Пришлите список — по одной песне в строке."
        )
        return

    if len(songs) < MIN_SONGS:
        await message.answer(
            f"Распознал песен: <b>{len(songs)}</b>.\n\n"
            f"Этого мало: нужно минимум {MIN_SONGS} уникальных песен для таблицы 6×6 "
            "и 49 для таблицы 7×7. Пришлите список побольше."
        )
        return

    await state.update_data(songs=songs, duplicates=duplicates)
    await state.set_state(Flow.size)

    lines = [f"✅ Принято песен: <b>{len(songs)}</b>."]
    if duplicates:
        lines.append(f"Дубликаты убраны: {duplicates}.")
    lines.append("")
    lines.append("<b>Шаг 2 из 4.</b> Выберите размер таблицы:")
    if len(songs) < 49:
        lines.append("")
        lines.append(
            f"Доступен только 6×6: для 7×7 нужно хотя бы 49 песен, а сейчас {len(songs)}."
        )

    await message.answer("\n".join(lines), reply_markup=size_keyboard(len(songs)))


# ---------------------------------------------------------------- команды


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Flow.songs)
    await message.answer(WELCOME_TEXT)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Сбросил. Чтобы начать заново, отправьте /start.")


# ---------------------------------------------------------------- шаг 1: список


@router.message(Flow.songs, F.document)
async def handle_document(message: Message, state: FSMContext, bot: Bot) -> None:
    document = message.document
    if document is None:
        return

    name = (document.file_name or "").lower()
    if not (
        name.endswith((".txt", ".csv"))
        or (document.mime_type or "").startswith("text/")
    ):
        await message.answer("Пришлите текстовый файл (.txt) или список сообщением.")
        return

    if document.file_size and document.file_size > 1024 * 1024:
        await message.answer("Файл слишком большой — пришлите список до 1 МБ.")
        return

    buffer = await bot.download(document)
    raw = buffer.getvalue() if isinstance(buffer, io.BytesIO) else bytes(buffer)
    text = None
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        await message.answer("Не смог прочитать файл. Сохраните его в UTF-8 и пришлите снова.")
        return

    await accept_song_list(message, state, text)


@router.message(Flow.songs, F.text)
async def handle_song_list(message: Message, state: FSMContext) -> None:
    await accept_song_list(message, state, message.text or "")


# ---------------------------------------------------------------- шаг 2: размер


@router.callback_query(F.data.startswith("size:"))
async def choose_size(call: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != Flow.size.state:
        await call.answer("Кнопка устарела. Начните заново: /start", show_alert=True)
        return

    data = await state.get_data()
    songs = data.get("songs") or []
    try:
        size = int((call.data or "").split(":", 1)[1])
    except (IndexError, ValueError):
        await call.answer("Не понял размер.", show_alert=True)
        return

    if size not in (6, 7) or len(songs) < size * size:
        await call.answer("Для такой таблицы не хватает песен.", show_alert=True)
        return

    await state.update_data(size=size)
    await state.set_state(Flow.count)
    await call.answer()

    if call.message:
        try:
            await call.message.edit_text(
                count_prompt(size, len(songs)), reply_markup=None
            )
        except TelegramAPIError:
            await call.message.answer(count_prompt(size, len(songs)))


@router.message(Flow.size, F.text)
async def choose_size_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    songs = data.get("songs") or []
    size = parse_size_text(message.text or "")

    if size is None:
        await message.answer(
            "Выберите размер кнопкой выше или напишите <code>6×6</code> либо <code>7×7</code>."
        )
        return

    if len(songs) < size * size:
        await message.answer(
            f"Для таблицы {size}×{size} нужно минимум {size * size} песен, "
            f"а в списке {len(songs)}. Выберите 6×6 или пришлите список побольше."
        )
        return

    await state.update_data(size=size)
    await state.set_state(Flow.count)
    await message.answer(count_prompt(size, len(songs)))


# ---------------------------------------------------------------- шаг 3: количество


@router.message(Flow.count, F.text)
async def choose_count(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    songs = data.get("songs") or []
    size = data.get("size")

    if not songs or not size:
        await message.answer("Данные потерялись. Начните заново: /start")
        await state.clear()
        return

    text = (message.text or "").strip()
    match = re.fullmatch(r"(\d{1,3})(?:\s*(?:стол\w*|таблиц\w*))?", text, flags=re.IGNORECASE)
    if not match:
        await message.answer("Введите количество таблиц числом, например: 10.")
        return

    count = int(match.group(1))
    limit = max_tables(len(songs), size)
    if not 1 <= count <= limit:
        await message.answer(
            f"Для {len(songs)} песен и таблицы {size}×{size} можно сделать "
            f"от 1 до {limit} таблиц. Введите число из этого диапазона."
        )
        return

    await state.update_data(count=count)
    await state.set_state(Flow.first_win)
    duplicates = int(data.get("duplicates") or 0)
    await message.answer(first_win_prompt(songs, size, count, duplicates))


# ---------------------------------------------------------------- шаг 4: первый билет


@router.message(Flow.first_win, F.text)
async def choose_first_win(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    songs = data.get("songs") or []
    size = data.get("size")
    count = data.get("count")

    if not songs or not size or not count:
        await message.answer("Данные потерялись. Начните заново: /start")
        await state.clear()
        return

    text = (message.text or "").strip()
    low, high = win_range(len(songs), size, count)
    number_match = re.fullmatch(r"№?\s*(\d{1,4})\s*[.)]?", text)

    if number_match:
        song_index = int(number_match.group(1))
    else:
        song_index, candidates = find_song_index(text, songs)
        if song_index is None:
            if candidates:
                preview = "\n".join(
                    f"№{index} — «{esc(songs[index - 1])}»" for index in candidates
                )
                await message.answer(
                    "Под это описание подходит несколько песен:\n\n"
                    f"{preview}\n\n"
                    "Напишите название точнее или введите номер песни."
                )
            else:
                await message.answer(
                    f"Не нашёл такую песню в списке. Введите номер от {low} до {high} "
                    "или название точнее."
                )
            return

    if not low <= song_index <= high:
        await message.answer(
            f"Песня №{song_index} не подходит: первый победный билет должен быть "
            f"на песне с №{low} по №{high}. Иначе правила игры не выполнятся."
        )
        return

    await state.update_data(first_win=song_index)
    await message.answer(
        f"🎯 Первый победный билет — песня <b>№{song_index}</b> "
        f"«{esc(songs[song_index - 1])}».\n\nСобираю таблицы…"
    )
    await generate_and_send(bot, state, message.chat.id)


# ---------------------------------------------------------------- после выдачи


@router.callback_query(F.data.startswith("more:"))
async def more_actions(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if await state.get_state() != Flow.ready.state:
        await call.answer("Кнопка устарела. Начните заново: /start", show_alert=True)
        return

    action = (call.data or "").split(":", 1)[1]
    data = await state.get_data()
    songs = data.get("songs") or []
    size = data.get("size")
    count = data.get("count")

    if not songs or not size or not count:
        await call.answer("Данные потерялись, начните заново.", show_alert=True)
        return

    chat_id = call.message.chat.id if call.message else call.from_user.id

    if action == "regen":
        await call.answer("Собираю новый вариант…")
        await generate_and_send(bot, state, chat_id)
        return

    if action == "win":
        await call.answer()
        await delete_sent(bot, state)
        await state.set_state(Flow.first_win)
        duplicates = int(data.get("duplicates") or 0)
        await bot.send_message(
            chat_id, first_win_prompt(songs, size, count, duplicates)
        )
        return

    if action == "size":
        await call.answer()
        await delete_sent(bot, state)
        await state.set_state(Flow.size)
        lines = ["<b>Шаг 2 из 4.</b> Выберите новый размер таблицы:"]
        if len(songs) < 49:
            lines.append("")
            lines.append(
                f"Доступен только 6×6: для 7×7 нужно хотя бы 49 песен, а сейчас {len(songs)}."
            )
        await bot.send_message(
            chat_id, "\n".join(lines), reply_markup=size_keyboard(len(songs))
        )
        return

    if action == "new":
        await call.answer()
        await delete_sent(bot, state)
        await state.clear()
        await state.set_state(Flow.songs)
        await bot.send_message(chat_id, WELCOME_TEXT)
        return

    await call.answer("Неизвестное действие.", show_alert=True)


@router.message()
async def fallback(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current == Flow.songs.state:
        await message.answer(
            "Пришлите список песен текстом — по одной в строке — или файлом .txt."
        )
        return
    if current in (Flow.count.state, Flow.first_win.state):
        await message.answer("Нужен текст. /cancel — сбросить, /help — подсказка.")
        return
    await message.answer("Не понял. /start — начать новую игру, /help — правила.")


# ---------------------------------------------------------------- запуск


async def main() -> None:
    token = load_token()

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать новую игру"),
            BotCommand(command="help", description="Правила и подсказки"),
            BotCommand(command="cancel", description="Сбросить ввод"),
        ]
    )

    logger.info("Бот запущен")
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await bot.session.close()


def run_selftest() -> int:
    """Проверяет, что в сборке есть генератор и Pillow, без обращения к Telegram."""

    import random

    songs = [f"Артист {i} — Песня {i}" for i in range(1, 51)]
    try:
        cards = build_cards(50, 6, 3, 10, rng=random.Random(0))
        payload = render_card(cards[0], songs)
    except Exception as exc:
        print(f"Самопроверка не прошла: {exc}")
        return 1

    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        print("Самопроверка не прошла: странный формат картинки.")
        return 1

    print(f"Самопроверка пройдена: таблица {len(payload)} байт.")
    return 0


def token_status() -> int:
    """Показывает, откуда взят токен, не раскрывая его целиком."""

    token, source = find_token()
    if not token:
        print("Токен не найден. Бот спросит его при запуске.")
        return 1

    masked = f"{token[:4]}…{token[-4:]}" if len(token) > 10 else "…"
    print(f"Токен найден ({masked}) — источник: {source}")
    return 0


if __name__ == "__main__":
    if "--check-token" in sys.argv:
        raise SystemExit(token_status())
    if "--selftest" in sys.argv:
        raise SystemExit(run_selftest())

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code:
            print(exc)
    except Exception:
        logger.exception("Бот остановился из-за ошибки")
        if getattr(sys, "frozen", False) and sys.stdin and sys.stdin.isatty():
            try:
                input("Нажмите Enter, чтобы закрыть окно…")
            except (EOFError, KeyboardInterrupt):
                pass
        raise SystemExit(1)
