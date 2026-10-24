"""Интеграционные тесты HTTP API: цензура, реклама, конфиг платформы."""

import asyncio
import tempfile

from aiohttp import test_utils

from game import engine, render
from game.config import Config
from game.storage import JsonStorage
from game.webapp import create_app


def _vk_config() -> Config:
    return Config(
        bot_token=None,
        bot_mode="polling",
        webhook_url=None,
        web_host="0.0.0.0",
        web_port=8080,
        secret=None,
        censor_mode="symbols",
        permadeath=False,
        vk_app_id=None,
        vk_secret=None,
    )


async def _client(tmp_dir: str) -> test_utils.TestClient:
    app = create_app(_vk_config(), JsonStorage(tmp_dir))
    server = test_utils.TestServer(app)
    client = test_utils.TestClient(server)
    await client.start_server()
    return client


def _run(coro):
    return asyncio.run(coro)


async def _post(client, path, payload):
    return await client.post(path, json=payload)


def test_state_creates_save():
    with tempfile.TemporaryDirectory() as tmp:
        async def scenario():
            client = await _client(tmp)
            try:
                resp = await _post(client, "/api/state", {"user_id": "u1"})
                assert resp.status == 200
                view = await resp.json()
                assert view["scene"]["id"] == "intro"
                assert "exhausted" in view
            finally:
                await client.close()

        _run(scenario())


def test_ad_reward_then_cooldown():
    with tempfile.TemporaryDirectory() as tmp:
        async def scenario():
            client = await _client(tmp)
            try:
                await _post(client, "/api/state", {"user_id": "u2"})
                first = await _post(client, "/api/ad/reward", {"user_id": "u2"})
                assert first.status == 200
                data = await first.json()
                assert any("Ролик просмотрен" in line for line in data["messages"])

                second = await _post(client, "/api/ad/reward", {"user_id": "u2"})
                assert second.status == 429
            finally:
                await client.close()

        _run(scenario())


def test_invalid_user_id_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        async def scenario():
            client = await _client(tmp)
            try:
                resp = await _post(client, "/api/state", {"user_id": "../../etc"})
                assert resp.status == 400
            finally:
                await client.close()

        _run(scenario())


def test_healthz():
    with tempfile.TemporaryDirectory() as tmp:
        async def scenario():
            client = await _client(tmp)
            try:
                resp = await client.get("/healthz")
                assert resp.status == 200
            finally:
                await client.close()

        _run(scenario())


def test_render_applies_censorship_in_vk_mode():
    state = engine.new_game("vk-censor")
    state.scene_id = "day6_inspector"
    raw = render.render_view(state, "off")
    assert "долбоёб" in raw["scene"]["text"]

    censored = render.render_view(state, "symbols")
    assert "долбоёб" not in censored["scene"]["text"]
    assert ";%:?*" in censored["scene"]["text"]


def test_render_exposes_exhausted_timestamp():
    state = engine.new_game("vk-ts")
    state.exhausted_until = 1_000_900
    view = render.render_view(state, "off")
    assert view["exhausted"] == 1_000_900


def test_render_includes_art_mapping():
    state = engine.new_game("art")
    engine.choose(state, 0)  # intro -> day1_act
    view = render.render_view(state, "off")
    assert view["art"]["background"].endswith("office.jpg")
    assert view["art"]["portrait"].endswith("petrovich.jpg")

    # у геологов свой фон-тайга
    state.scene_id = "day8_geologists"
    view = render.render_view(state, "off")
    assert view["art"]["background"].endswith("taiga.jpg")

    # случайная сцена без явного портрета
    state.scene_id = "r_coffee"
    view = render.render_view(state, "off")
    assert view["art"]["portrait"] is None
    assert view["art"]["background"].endswith("office.jpg")
