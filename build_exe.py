"""Сборка автономного Windows-бота в один .exe.

Запуск:
    python build_exe.py

Токен берётся из переменной окружения BOT_TOKEN или из файла .env в корне
проекта и вшивается в исполняемый файл. Готовый файл:
    dist/MusicLottoBot.exe

Его можно отдать любому человеку — Python и установка зависимостей не нужны.
Токен внутри файла, поэтому одновременно может работать только один экземпляр
бота с этим токеном.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
NAME = "MusicLottoBot"


def read_token() -> str:
    env_token = (os.getenv("BOT_TOKEN") or "").strip()
    if env_token:
        return env_token

    env_file = ROOT / ".env"
    if not env_file.is_file():
        raise SystemExit(
            "Не найден токен. Создайте .env в корне проекта со строкой:\n"
            "BOT_TOKEN=123456789:AA..."
        )

    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "BOT_TOKEN":
            token = value.strip().strip("\"'")
            if token:
                return token

    raise SystemExit("В .env нет заполненного BOT_TOKEN.")


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Устанавливаю PyInstaller…")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "pyinstaller>=6"],
            check=True,
        )


def main() -> int:
    if os.name != "nt":
        print("Сборка .exe рассчитана на Windows.")
        return 1

    token = read_token()
    ensure_pyinstaller()

    BUILD_DIR.mkdir(exist_ok=True)
    token_file = BUILD_DIR / "token.txt"
    token_file.write_text(token + "\n", encoding="utf-8")

    sep = os.pathsep  # ";" на Windows
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",
        "--name",
        NAME,
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR / "pyinstaller"),
        "--specpath",
        str(BUILD_DIR),
        "--add-data",
        f"{token_file}{sep}.",
        "--collect-submodules",
        "aiogram",
        "--exclude-module",
        "pytest",
        str(ROOT / "bot.py"),
    ]

    print("Собираю exe, это может занять пару минут…")
    try:
        subprocess.run(args, cwd=ROOT, check=True)
    finally:
        token_file.unlink(missing_ok=True)

    exe = DIST_DIR / f"{NAME}.exe"
    if not exe.is_file():
        print("Сборка не дала файл dist/MusicLottoBot.exe.")
        return 1

    size_mb = exe.stat().st_size / (1024 * 1024)
    print(f"\nГотово: {exe} ({size_mb:.1f} МБ)")
    print("Проверка: dist\\MusicLottoBot.exe --selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
