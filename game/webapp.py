"""Веб-версия игры на aiohttp: браузер + Telegram Mini App + webhook бота.

Один процесс обслуживает:
  GET  /              — страница игры (web/index.html);
  POST /api/state     — получить/создать сохранение;
  POST /api/choose    — сделать выбор в сцене;
  POST /api/use       — использовать расходник;
  POST /api/reset     — начать заново;
  POST /tg/webhook    — входящие обновления Telegram (режим webhook);
  GET  /healthz       — проверка живости для хостинга.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from . import engine, render
from . import vk as vk_platform
from .config import Config
from .storage import Storage

logger = logging.getLogger("egor.web")

WEB_DIR = Path(__file__).parent.parent / "web"
_USER_ID_RE = re.compile(r"^[A-Za-z0-9_@.:-]{1,64}$")


# ---------------------------------------------------------------------------
# Проверка подписи Telegram Mini App
# https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
# ---------------------------------------------------------------------------

def verify_init_data(init_data: str, bot_token: str) -> dict | None:
    """Проверяет HMAC-подпись initData. Возвращает данные пользователя или None."""
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            return None
        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(pairs.items())
        )
        secret_key = hmac.new(
            b"WebAppData", bot_token.encode(), hashlib.sha256
        ).digest()
        calculated = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        return json.loads(pairs["user"]) if "user" in pairs else {}
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


async def _resolve_user(request: web.Request) -> str:
    """Достаёт user_id из тела запроса: сначала подпись Mini App, потом явный id."""
    body = await request.json()
    config: Config = request.app["config"]

    init_data = body.get("initData")
    if init_data and config.secret:
        tg_user = verify_init_data(init_data, config.secret)
        if tg_user and tg_user.get("id"):
            return f"tg:{tg_user['id']}"
        if init_data:
            raise web.HTTPBadRequest(reason="Invalid Telegram initData")

    user_id = str(body.get("user_id", ""))
    if not _USER_ID_RE.match(user_id):
        raise web.HTTPBadRequest(reason="Invalid user_id")
    return user_id


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

async def api_state(request: web.Request) -> web.Response:
    config: Config = request.app["config"]
    user_id = await _resolve_user(request)
    storage: Storage = request.app["storage"]
    state = await storage.load(user_id)
    if state is None:
        state = engine.new_game(user_id)
        await storage.save(state)
    # Вдруг таймер восстановления уже истёк, пока игрок отсутствовал
    engine.tick(state)
    await storage.save(state)
    return web.json_response(render.render_view(state, config.censor_mode))


async def api_choose(request: web.Request) -> web.Response:
    user_id = await _resolve_user(request)
    body = await request.json()
    try:
        option_index = int(body["option_index"])
    except (KeyError, TypeError, ValueError):
        raise web.HTTPBadRequest(reason="option_index required")

    storage: Storage = request.app["storage"]
    state = await storage.load(user_id)
    if state is None:
        state = engine.new_game(user_id)
    if state.over:
        raise web.HTTPConflict(reason="Game over, reset first")

    scene = engine.get_scene(state)
    if not 0 <= option_index < len(scene["options"]):
        raise web.HTTPBadRequest(reason="Bad option index")

    config: Config = request.app["config"]
    result = engine.choose(state, option_index, permadeath=config.permadeath)
    state.last_lines = result.lines
    await storage.save(state)
    return web.json_response(
        {
            "messages": result.lines,
            "view": render.render_view(state, config.censor_mode),
        }
    )


async def api_use(request: web.Request) -> web.Response:
    user_id = await _resolve_user(request)
    body = await request.json()
    item_id = str(body.get("item_id", ""))
    if not re.fullmatch(r"[a-z_]+", item_id):
        raise web.HTTPBadRequest(reason="Bad item_id")

    config: Config = request.app["config"]
    storage: Storage = request.app["storage"]
    state = await storage.load(user_id)
    if state is None:
        raise web.HTTPNotFound(reason="No save")
    lines = engine.use_item(state, item_id, permadeath=config.permadeath)
    state.last_lines = lines
    await storage.save(state)
    return web.json_response(
        {"messages": lines, "view": render.render_view(state, config.censor_mode)}
    )


async def api_reset(request: web.Request) -> web.Response:
    config: Config = request.app["config"]
    user_id = await _resolve_user(request)
    storage: Storage = request.app["storage"]
    state = engine.new_game(user_id)
    await storage.save(state)
    return web.json_response(render.render_view(state, config.censor_mode))


async def api_ad_reward(request: web.Request) -> web.Response:
    """Награда за просмотр rewarded-ролика. Кулдаун проверяет движок."""
    config: Config = request.app["config"]
    user_id = await _resolve_user(request)
    storage: Storage = request.app["storage"]
    state = await storage.load(user_id)
    if state is None:
        raise web.HTTPNotFound(reason="No save")
    ok, lines = engine.grant_ad_reward(state)
    state.last_lines = lines
    if not ok:
        return web.json_response({"error": lines[0]}, status=429)
    await storage.save(state)
    return web.json_response(
        {"messages": lines, "view": render.render_view(state, config.censor_mode)}
    )


async def healthz(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


# ---------------------------------------------------------------------------
# VK Mini Apps: stateless-эндпоинты (состояние хранится в VK Storage)
# ---------------------------------------------------------------------------

async def _vk_context(request: web.Request):
    """Проверяет подпись запуска и разворачивает сохранение из тела запроса."""
    config: Config = request.app["config"]
    body = await request.json()
    launch = body.get("launch")
    if not isinstance(launch, dict):
        raise web.HTTPBadRequest(reason="launch params required")
    ok, user_id, reason = vk_platform.verify_launch_params(
        launch, config.vk_app_id or "", config.vk_secret or ""
    )
    if not ok:
        raise web.HTTPUnauthorized(reason=reason)

    storage_key = f"vk:{user_id}"
    raw_save = body.get("save")
    if raw_save:
        try:
            state = vk_platform.load_compact(raw_save, storage_key)
        except (ValueError, TypeError, json.JSONDecodeError):
            raise web.HTTPBadRequest(reason="Bad save payload")
    else:
        state = engine.new_game(storage_key)
    engine.tick(state)
    return config, state


def _vk_payload(state, config: Config, messages: list[str] | None = None) -> dict:
    return {
        "view": render.render_view(state, config.censor_mode),
        "save": vk_platform.dump_compact(state),
        "messages": messages or [],
    }


async def vk_state(request: web.Request) -> web.Response:
    config, state = await _vk_context(request)
    return web.json_response(_vk_payload(state, config))


async def vk_choose(request: web.Request) -> web.Response:
    config, state = await _vk_context(request)
    body = await request.json()
    try:
        option_index = int(body["option_index"])
    except (KeyError, TypeError, ValueError):
        raise web.HTTPBadRequest(reason="option_index required")
    scene = engine.get_scene(state)
    if not 0 <= option_index < len(scene["options"]):
        raise web.HTTPBadRequest(reason="Bad option index")
    result = engine.choose(state, option_index, permadeath=False)
    return web.json_response(_vk_payload(state, config, result.lines))


async def vk_use(request: web.Request) -> web.Response:
    config, state = await _vk_context(request)
    body = await request.json()
    item_id = str(body.get("item_id", ""))
    if not re.fullmatch(r"[a-z_]+", item_id):
        raise web.HTTPBadRequest(reason="Bad item_id")
    lines = engine.use_item(state, item_id, permadeath=False)
    return web.json_response(_vk_payload(state, config, lines))


async def vk_ad(request: web.Request) -> web.Response:
    config, state = await _vk_context(request)
    ok, lines = engine.grant_ad_reward(state)
    if not ok:
        return web.json_response({"error": lines[0]}, status=429)
    return web.json_response(_vk_payload(state, config, lines))


async def vk_reset(request: web.Request) -> web.Response:
    config, state = await _vk_context(request)
    fresh = engine.new_game(state.user_id)
    return web.json_response(_vk_payload(fresh, config))


async def telegram_webhook(request: web.Request) -> web.Response:
    """Точка входа для Telegram webhook — скармливаем апдейт диспетчеру."""
    bot = request.app.get("bot")
    dp = request.app.get("dp")
    if bot is None or dp is None:
        raise web.HTTPNotFound()
    data = await request.json()
    await dp.feed_webhook_update(bot, data)
    return web.json_response({"ok": True})


# ---------------------------------------------------------------------------
# Сборка приложения
# ---------------------------------------------------------------------------

@web.middleware
async def json_errors(request: web.Request, handler):
    """Любая HTTP-ошибка API отвечает JSON-ом, а не plain text."""
    try:
        return await handler(request)
    except web.HTTPException as exc:
        if request.path.startswith("/api/"):
            return web.json_response(
                {"error": exc.reason or exc.text or "error"}, status=exc.status
            )
        raise


# Типы, которые обязаны обновляться сразу после деплоя: залипший в кэше
# WebView старый CSS/JS уже приводил к неработающим кнопкам в VK.
_NO_CACHE_SUFFIXES = (".js", ".css", ".html")


@web.middleware
async def no_cache_app_shell(request: web.Request, handler):
    response = await handler(request)
    path = request.path
    if path == "/" or any(path.endswith(suffix) for suffix in _NO_CACHE_SUFFIXES):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


def create_app(config: Config, storage: Storage, bot=None, dp=None) -> web.Application:
    app = web.Application(middlewares=[json_errors, no_cache_app_shell])
    app["config"] = config
    app["storage"] = storage
    app["bot"] = bot
    app["dp"] = dp

    app.router.add_post("/api/state", api_state)
    app.router.add_post("/api/choose", api_choose)
    app.router.add_post("/api/use", api_use)
    app.router.add_post("/api/reset", api_reset)
    app.router.add_post("/api/ad/reward", api_ad_reward)
    app.router.add_post("/api/vk/state", vk_state)
    app.router.add_post("/api/vk/choose", vk_choose)
    app.router.add_post("/api/vk/use", vk_use)
    app.router.add_post("/api/vk/ad", vk_ad)
    app.router.add_post("/api/vk/reset", vk_reset)
    app.router.add_get("/healthz", healthz)
    app.router.add_post("/tg/webhook", telegram_webhook)

    # Статика фронтенда
    app.router.add_static("/static", WEB_DIR, name="static")
    app.router.add_static(
        "/sounds", WEB_DIR / "static" / "sounds", name="sounds"
    )
    app.router.add_static("/img", WEB_DIR / "static" / "img", name="img")

    async def index(_request: web.Request) -> web.FileResponse:
        return web.FileResponse(WEB_DIR / "index.html")

    app.router.add_get("/", index)
    return app
