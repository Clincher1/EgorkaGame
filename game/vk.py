"""Интеграция с VK Mini Apps.

Две вещи, которые нужны серверу:

1. :func:`verify_launch_params` — проверка подписи ``sign`` у параметров запуска
   приложения (https://dev.vk.com/ru/mini-apps/development/launch-params):
   подделать запуск от чужого VK ID без секретного ключа приложения нельзя.
2. :func:`dump_compact` / :func:`load_compact` — компактная сериализация
   состояния под лимит VK Storage (4096 байт на одно значение): короткие
   ключи, без логов и last_lines, пустые коллекции выбрасываются.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from urllib.parse import urlencode

from .models import GameState

VK_STORAGE_LIMIT = 4096


# ---------------------------------------------------------------------------
# Проверка подписи запуска
# ---------------------------------------------------------------------------

def _canonical_query(params: dict) -> str:
    """Каноническая строка по спецификации VK: только ключи vk_*,
    лексикографическая сортировка, urlencode (как в официальном примере
    VKCOM/vk-apps-launch-params/examples/python3.py)."""
    ordered = {k: params[k] for k in sorted(params) if k.startswith("vk_")}
    return urlencode(ordered, doseq=True)


def sign_launch_params(params: dict, secure_key: str) -> str:
    """Подписывает параметры запуска. Эталон — официальный алгоритм VK:
    HMAC-SHA256 с самим защищённым ключом (без хеширования ключа),
    base64url без padding."""
    digest = hmac.new(
        secure_key.encode(),
        _canonical_query(params).encode(),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def verify_launch_params(
    params: dict, app_id: str | int, secure_key: str
) -> tuple[bool, int | None, str]:
    """Проверяет подписанные параметры запуска VK Mini App.

    Возвращает (успех, vk_user_id, причина_ошибки).
    """
    if not app_id or not secure_key:
        return False, None, "VK не сконфигурирован на сервере"

    sign = params.get("sign")
    if not sign:
        return False, None, "Нет подписи sign"

    if str(params.get("vk_app_id")) != str(app_id):
        return False, None, "Чужой vk_app_id"

    if not any(k.startswith("vk_") for k in params):
        return False, None, "Нет параметров vk_*"

    expected = sign_launch_params(params, secure_key)
    if not hmac.compare_digest(expected, str(sign)):
        return False, None, "Подпись не совпала"

    try:
        user_id = int(params.get("vk_user_id"))
    except (TypeError, ValueError):
        return False, None, "Нет vk_user_id"
    return True, user_id, ""


# ---------------------------------------------------------------------------
# Компактное сохранение для VK Storage
# ---------------------------------------------------------------------------

# Короткие имена полей: в JSON каждая буква ключа платная при лимите 4 КБ
_KEY_MAP = {
    "user_id": "u",
    "day": "d",
    "energy": "e",
    "mood": "m",
    "authority": "a",
    "money": "c",
    "skill_levels": "l",
    "skill_xp": "x",
    "inventory": "i",
    "charges": "h",
    "flags": "f",
    "scene_id": "s",
    "seen_scenes": "n",
    "exhausted_until": "eu",
    "exhausted_scene": "es",
    "over": "o",
    "ending": "g",
}
_REVERSE_MAP = {short: full for full, short in _KEY_MAP.items()}


def dump_compact(state: GameState) -> str:
    """Сериализует состояние в компактную JSON-строку для VK Storage."""
    full = state.to_dict()
    compact: dict = {"v": 1}
    for full_name, short in _KEY_MAP.items():
        value = full.get(full_name)
        # Пропускаем пустые/дефолтные коллекции и None
        if value in (None, {}, [], ""):
            continue
        if full_name == "flags":
            # Служебные флаги переходов не нужны при следующем запуске
            value = {k: v for k, v in value.items() if not k.startswith("_")}
            if not value:
                continue
        compact[short] = value
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def load_compact(payload: str, fallback_user_id: str) -> GameState:
    """Разворачивает компактную строку обратно в GameState."""
    compact = json.loads(payload)
    full: dict = {"user_id": fallback_user_id}
    for short, value in compact.items():
        if short == "v":
            continue
        full_name = _REVERSE_MAP.get(short)
        if full_name:
            full[full_name] = value
    return GameState.from_dict(full)


def fits_storage(state: GameState) -> bool:
    """Помещается ли сохранение в лимит VK Storage."""
    return len(dump_compact(state).encode("utf-8")) <= VK_STORAGE_LIMIT
