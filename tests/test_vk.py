"""Тесты VK-подписи, компактного сохранения и stateless API."""

import base64
import hashlib
import hmac
import json
import random
import tempfile

from aiohttp import test_utils

from game import engine
from game.config import Config
from game.content import ALL_SCENES, ITEMS
from game.storage import JsonStorage
from game.vk import (
    VK_STORAGE_LIMIT,
    dump_compact,
    fits_storage,
    load_compact,
    verify_launch_params,
)
from game.webapp import create_app

APP_ID = "777001"
SECRET = "test-secure-key"


def _sign(params: dict) -> str:
    check = {k: v for k, v in params.items() if k != "sign"}
    dcs = "&".join(f"{k}={check[k]}" for k in sorted(check))
    secret = hashlib.sha256(SECRET.encode()).digest()
    digest = hmac.new(secret, dcs.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _launch(user_id: int = 555, app_id: str = APP_ID) -> dict:
    params = {"vk_app_id": app_id, "vk_user_id": str(user_id), "vk_platform": "mobile"}
    params["sign"] = _sign(params)
    return params


# --------------------------------------------------------------------------
# Подпись launch params
# --------------------------------------------------------------------------

def test_valid_launch_signature():
    ok, user_id, reason = verify_launch_params(_launch(), APP_ID, SECRET)
    assert ok and user_id == 555 and reason == ""


def test_tampered_params_rejected():
    launch = _launch()
    launch["vk_user_id"] = "999"  # поменяли, подпись осталась старая
    ok, user_id, reason = verify_launch_params(launch, APP_ID, SECRET)
    assert not ok and user_id is None
    assert "Подпись" in reason


def test_foreign_app_id_rejected():
    launch = _launch(app_id="1")
    ok, _, reason = verify_launch_params(launch, APP_ID, SECRET)
    assert not ok and "vk_app_id" in reason


def test_missing_sign_rejected():
    ok, _, reason = verify_launch_params(
        {"vk_app_id": APP_ID, "vk_user_id": "1"}, APP_ID, SECRET
    )
    assert not ok and "sign" in reason


# --------------------------------------------------------------------------
# Компактное сохранение
# --------------------------------------------------------------------------

def _heavy_state() -> engine.GameState:
    """Максимально «прожорливое» состояние: все предметы, сцены, флаги."""
    state = engine.new_game("vk:heavy")
    for item_id in ITEMS:
        state.add_item(item_id)
        if ITEMS[item_id].get("consumable"):
            state.charges[item_id] = 9
    for scene_id in ALL_SCENES:
        if scene_id not in state.seen_scenes:
            state.seen_scenes.append(scene_id)
    for i in range(15):
        state.set_flag(f"flag_{i}", i)
    state.set_flag("absurd_count", 7)
    state.day = 10
    state.exhausted_until = 2_000_000_000
    state.exhausted_scene = "day5_sim"
    state.last_lines = ["эти строки не должны попасть в compact"] * 5
    state.log = ["лог тоже не должен"] * 10
    return state


def test_compact_roundtrip():
    state = _heavy_state()
    payload = dump_compact(state)
    restored = load_compact(payload, state.user_id)
    assert restored.day == state.day
    assert restored.inventory == state.inventory
    assert restored.charges == state.charges
    assert restored.scene_id == state.scene_id
    assert restored.exhausted_until == state.exhausted_until
    assert restored.flag("absurd_count") == 7
    # логи в compact не сериализуются
    assert restored.last_lines == []


def test_compact_fits_vk_limit():
    state = _heavy_state()
    size = len(dump_compact(state).encode("utf-8"))
    assert size < VK_STORAGE_LIMIT, f"{size} байт > лимита {VK_STORAGE_LIMIT}"
    assert fits_storage(state)


def test_compact_smaller_than_full():
    state = _heavy_state()
    full = len(json.dumps(state.to_dict(), ensure_ascii=False).encode())
    compact = len(dump_compact(state).encode())
    assert compact < full * 0.7


def test_real_playthrough_fits_storage():
    rng = random.Random(42)
    state = engine.new_game("vk:real")
    while not state.over:
        scene = engine.get_scene(state)
        opts = [o["index"] for o in engine.annotate_options(state, scene) if o["available"]]
        engine.choose(state, rng.choice(opts), rng=rng, permadeath=False)
    assert fits_storage(state)


# --------------------------------------------------------------------------
# Stateless-эндпоинты
# --------------------------------------------------------------------------

def _app():
    config = Config(
        bot_token=None,
        bot_mode="polling",
        webhook_url=None,
        web_host="0.0.0.0",
        web_port=8080,
        secret=None,
        censor_mode="symbols",
        permadeath=False,
        vk_app_id=APP_ID,
        vk_secret=SECRET,
    )
    with tempfile.TemporaryDirectory() as tmp:
        return create_app(config, JsonStorage(tmp))


def test_vk_endpoints_happy_path():
    import asyncio

    async def scenario():
        client = test_utils.TestClient(test_utils.TestServer(_app()))
        await client.start_server()
        try:
            # старт без сохранения
            resp = await client.post("/api/vk/state", json={"launch": _launch()})
            assert resp.status == 200
            data = await resp.json()
            assert data["view"]["scene"]["id"] == "intro"
            assert len(data["save"]) < VK_STORAGE_LIMIT

            # первый ход с сохранением, полученным от клиента
            resp = await client.post(
                "/api/vk/choose",
                json={"launch": _launch(), "save": data["save"], "option_index": 0},
            )
            assert resp.status == 200
            moved = await resp.json()
            assert moved["view"]["scene"]["id"] == "day1_act"

            # поддельная подпись отлетает 401
            bad = _launch()
            bad["sign"] = "aaa"
            resp = await client.post("/api/vk/state", json={"launch": bad})
            assert resp.status == 401

            # битое сохранение — 400
            resp = await client.post(
                "/api/vk/state",
                json={"launch": _launch(), "save": "{не json"},
            )
            assert resp.status == 400
        finally:
            await client.close()

    asyncio.run(scenario())
