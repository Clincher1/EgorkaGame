"""Тесты VK-подписи, компактного сохранения и stateless API."""

import json
import random
import tempfile
from urllib.parse import parse_qsl, urlparse

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
    sign_launch_params,
    verify_launch_params,
)
from game.webapp import create_app

APP_ID = "777001"
SECRET = "test-secure-key"


def _sign(params: dict) -> str:
    return sign_launch_params(params, SECRET)


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


def test_official_vk_vector_accepted():
    # Эталонный вектор из репозитория VKCOM/vk-apps-launch-params
    # (examples/python3.py): защищённый ключ, реальный формат launch params.
    url = (
        "https://example.com/?vk_user_id=494075&vk_app_id=6736218"
        "&vk_is_app_user=1&vk_are_notifications_enabled=1&vk_language=ru"
        "&vk_access_token_settings=&vk_platform=android"
        "&sign=htQFduJpLxz7ribXRZpDFUH-XEUhC9rBPTJkjUFEkRA"
    )
    params = dict(parse_qsl(urlparse(url).query, keep_blank_values=True))
    ok, user_id, reason = verify_launch_params(
        params, app_id="6736218", secure_key="wvl68m4dR1UpLrVRli"
    )
    assert ok, reason
    assert user_id == 494075


def test_non_vk_params_ignored_in_signature():
    # Лишние ключи без префикса vk_ (включая sign) не участвуют в подписи.
    params = _launch()
    params["custom_param"] = "anything"
    ok, _, reason = verify_launch_params(params, APP_ID, SECRET)
    assert ok, reason


def test_roundtrip_sign_and_verify():
    params = {
        "vk_app_id": APP_ID,
        "vk_user_id": "392173456",
        "vk_platform": "desktop_web",
        "vk_ts": "1792867232",
        "vk_ref": "snippet_im",
        "vk_access_token_settings": "",
    }
    signed = dict(params)
    signed["sign"] = sign_launch_params(params, SECRET)
    ok, user_id, _ = verify_launch_params(signed, APP_ID, SECRET)
    assert ok and user_id == 392173456


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
