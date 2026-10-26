from __future__ import annotations

import asyncio
import random
from types import SimpleNamespace

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

import bot as bot_module
from music_lotto.generator import build_cards


class RenderErrorStub(Exception):
    pass


class FakeBot:
    def __init__(self) -> None:
        self.messages = []
        self.photos = []
        self.documents = []
        self.deleted = []
        self._id = 0

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        self.messages.append(
            SimpleNamespace(
                chat_id=chat_id, text=text, reply_markup=reply_markup, **kwargs
            )
        )
        return SimpleNamespace(message_id=self._next_id())

    async def send_photo(self, chat_id, photo, caption=None, **kwargs):
        self.photos.append(SimpleNamespace(chat_id=chat_id, photo=photo, caption=caption))
        return SimpleNamespace(message_id=self._next_id())

    async def send_document(self, chat_id, document, caption=None, **kwargs):
        self.documents.append(
            SimpleNamespace(chat_id=chat_id, document=document, caption=caption)
        )
        return SimpleNamespace(message_id=self._next_id())

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


async def make_state(data: dict) -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=1, user_id=1)
    state = FSMContext(storage=storage, key=key)
    await state.update_data(**data)
    return state


def test_deliver_cards_sends_images_and_key(monkeypatch):
    monkeypatch.setattr(bot_module, "SEND_DELAY", 0)

    songs = [f"Артист {i} — Песня {i}" for i in range(1, 51)]
    cards = build_cards(50, 6, 5, 20, rng=random.Random(11))

    async def scenario():
        state = await make_state(
            {"songs": songs, "size": 6, "count": 5, "first_win": 20}
        )
        fake = FakeBot()
        await bot_module.deliver_cards(fake, state, 1, cards, songs, 20)
        return fake, await state.get_data()

    fake, stored = asyncio.run(scenario())

    assert len(fake.photos) == 5
    assert len(fake.messages) == 2  # вступление и ключ
    assert fake.messages[0].text.startswith("🎲")
    assert fake.messages[-1].text.startswith("🔑")
    assert fake.messages[-1].reply_markup is not None
    assert not fake.documents

    assert len(stored["sent_ids"]) == 7
    assert stored["chat_id"] == 1


def test_deliver_cards_falls_back_to_text_file(monkeypatch):
    monkeypatch.setattr(bot_module, "SEND_DELAY", 0)

    def broken_render(*args, **kwargs):
        raise RenderErrorStub("нет шрифта")

    monkeypatch.setattr(bot_module, "render_card", broken_render)

    songs = [f"Артист {i} — Песня {i}" for i in range(1, 51)]
    cards = build_cards(50, 6, 2, 30, rng=random.Random(12))

    async def scenario():
        state = await make_state(
            {"songs": songs, "size": 6, "count": 2, "first_win": 30}
        )
        fake = FakeBot()
        await bot_module.deliver_cards(fake, state, 1, cards, songs, 30)
        return fake

    fake = asyncio.run(scenario())

    assert not fake.photos
    assert len(fake.documents) == 1
    assert "Таблица 1" in fake.documents[0].document.data.decode("utf-8")


def test_delete_sent_removes_stored_messages():
    async def scenario():
        state = await make_state({"chat_id": 5, "sent_ids": [1, 2, 3]})
        fake = FakeBot()
        await bot_module.delete_sent(fake, state)
        return fake, await state.get_data()

    fake, stored = asyncio.run(scenario())

    assert fake.deleted == [(5, 1), (5, 2), (5, 3)]
    assert stored["sent_ids"] == []
