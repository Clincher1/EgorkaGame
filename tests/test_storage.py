"""Тесты файлового хранилища."""

import asyncio

from game import engine
from game.storage import JsonStorage, safe_filename


def test_safe_filename():
    assert safe_filename("tg:12345/../etc") == "tg_12345_.._etc"
    assert safe_filename(777) == "777"


def test_json_storage_roundtrip(tmp_path):
    storage = JsonStorage(str(tmp_path))
    state = engine.new_game("tg:42")
    state.energy = 33
    state.set_flag("taiga", True)

    asyncio.run(storage.save(state))
    loaded = asyncio.run(storage.load("tg:42"))

    assert loaded is not None
    assert loaded.user_id == "tg:42"
    assert loaded.energy == 33
    assert loaded.flag("taiga") is True
    assert loaded.has_item("flask")


def test_json_storage_missing_and_corrupt(tmp_path):
    storage = JsonStorage(str(tmp_path))
    assert asyncio.run(storage.load("nobody")) is None

    (tmp_path / "broken.json").write_text("{это не json", encoding="utf-8")
    assert asyncio.run(storage.load("broken")) is None


def test_json_storage_delete(tmp_path):
    storage = JsonStorage(str(tmp_path))
    state = engine.new_game("u1")
    asyncio.run(storage.save(state))
    asyncio.run(storage.delete("u1"))
    assert asyncio.run(storage.load("u1")) is None
