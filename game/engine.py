"""Игровой движок: применяет выбор игрока к состоянию.

Движок ничего не знает про Telegram и HTTP — только данные и правила.
Поэтому он полностью покрывается юнит-тестами и используется и ботом,
и веб-версией.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from .content import (
    ALL_SCENES,
    CONSUME_EFFECTS,
    DAY_SCENES,
    ENDINGS,
    ITEMS,
    RANDOM_EVENT_CHANCE,
    RANDOM_SCENES,
    START_CHARGES,
    START_ITEMS,
    ZERO_ENDING,
)
from .models import SKILLS, STAT_MAX, GameState

# Усталость за рабочий день и восстановление вечером
FATIGUE_ENERGY = 10
FATIGUE_MOOD = 8
REST_ENERGY = 8
REST_MOOD = 5

# VK-режим: истощение вместо мгновенной концовки
EXHAUSTED_SCENE = "exhausted_rest"
RECOVERY_SECONDS = 15 * 60       # сколько Егор восстанавливается сам
RECOVERY_REFILL = 45             # до какого уровня поднимаются ресурсы
AD_REWARD_COOLDOWN = 60          # антинакрутка: не чаще ролика раз в минуту
AD_REWARD_ENERGY = 35            # награда за просмотр рекламы
AD_REWARD_MOOD = 25


@dataclass
class ChoiceResult:
    """Что произошло после выбора."""

    lines: list[str]
    state: GameState
    scene: dict
    ended: bool


# ---------------------------------------------------------------------------
# Создание игры
# ---------------------------------------------------------------------------

def new_game(user_id: str | int) -> GameState:
    state = GameState(user_id=str(user_id))
    for item in START_ITEMS:
        state.add_item(item)
    state.charges.update(START_CHARGES)
    state.scene_id = "intro"
    return state


def get_scene(state: GameState) -> dict:
    """Текущая сцена (или заглушка-концовка, если игра окончена)."""
    if state.over:
        ending = ENDINGS[state.ending]  # type: ignore[index]
        return {
            "id": "ending",
            "emoji": ending["emoji"],
            "title": ending["title"],
            "text": ending["text"],
            "options": [],
        }
    scene = dict(ALL_SCENES[state.scene_id])
    scene.setdefault("id", state.scene_id)
    return scene


# ---------------------------------------------------------------------------
# Доступность вариантов выбора
# ---------------------------------------------------------------------------

def check_requirements(state: GameState, requires: dict | None) -> tuple[bool, str]:
    """Проверяет блок «requires». Возвращает (можно_ли_выбрать, причина)."""
    if not requires:
        return True, ""

    if "item" in requires and not state.has_item(requires["item"]):
        return False, f"Нужен предмет: {ITEMS[requires['item']]['name']}"

    if "no_item" in requires and state.has_item(requires["no_item"]):
        return False, "Уже куплено"

    if "charge" in requires and state.charges.get(requires["charge"], 0) <= 0:
        return False, "Заряды закончились"

    if "money" in requires and state.money < requires["money"]:
        return False, f"Не хватает денег: нужно {requires['money']} ₽"

    if "authority" in requires and state.authority < requires["authority"]:
        return False, f"Нужен авторитет ≥ {requires['authority']}"

    if "skill" in requires:
        skill_id, min_level = requires["skill"]
        if state.skill_levels.get(skill_id, 0) < min_level:
            return False, f"Нужен навык «{SKILLS[skill_id]}» уровня {min_level}"

    if "skill_total" in requires:
        total = sum(state.skill_levels.values())
        if total < requires["skill_total"]:
            return False, f"Нужно суммарно {requires['skill_total']} уровней навыков"

    if "flag" in requires:
        name, expected = requires["flag"]
        if state.flag(name) != expected:
            return False, "Условие сюжета не выполнено"

    return True, ""


def annotate_options(state: GameState, scene: dict) -> list[dict]:
    """Список вариантов с пометками доступности для UI."""
    result = []
    for index, option in enumerate(scene["options"]):
        ok, reason = check_requirements(state, option.get("requires"))
        result.append(
            {
                "index": index,
                "available": ok,
                "reason": reason,
                "hint": option.get("hint", ""),
                "label": option["label"],
            }
        )
    return result


# ---------------------------------------------------------------------------
# Применение эффектов
# ---------------------------------------------------------------------------

def _apply_effects(state: GameState, effects: dict) -> list[str]:
    lines: list[str] = []
    if not effects:
        return lines

    for resource in ("energy", "mood", "authority", "money"):
        if effects.get(resource):
            delta = effects[resource]
            setattr(state, resource, getattr(state, resource) + delta)
            names = {
                "energy": "Энергия",
                "mood": "Настроение",
                "authority": "Авторитет",
                "money": "Деньги",
            }
            unit = " ₽" if resource == "money" else ""
            sign = "+" if delta > 0 else ""
            lines.append(f"{names[resource]}: {sign}{delta}{unit}")

    for skill, amount in effects.get("xp", {}).items():
        lines.extend(state.add_xp(skill, amount))

    if "add_item" in effects:
        items = effects["add_item"]
        if isinstance(items, str):
            items = [items]
        for item_id in items:
            state.add_item(item_id)
            lines.append(f"🎒 Получен предмет: {ITEMS[item_id]['emoji']} {ITEMS[item_id]['name']}")

    if "remove_item" in effects:
        item_id = effects["remove_item"]
        if state.has_item(item_id):
            state.remove_item(item_id)
            lines.append(f"❌ Потрачен предмет: {ITEMS[item_id]['name']}")

    if "add_charge" in effects:
        for item_id, amount in effects["add_charge"].items():
            state.charges[item_id] = state.charges.get(item_id, 0) + amount
            lines.append(f"➕ Зарядов «{ITEMS[item_id]['name']}»: +{amount}")

    if "use_charge" in effects:
        item_id = effects["use_charge"]
        state.charges[item_id] = max(0, state.charges.get(item_id, 0) - 1)
        left = state.charges[item_id]
        lines.append(f"🥃 Использован заряд «{ITEMS[item_id]['name']}» (осталось {left})")
        if left == 0 and item_id in state.inventory:
            # Пустую фляжку не выбрасываем — её можно пополнить по сюжету
            pass

    for name, value in effects.get("flags", {}).items():
        state.set_flag(name, value)

    if "absurd" in effects:
        count = int(state.flag("absurd_count", 0)) + effects["absurd"]
        state.set_flag("absurd_count", count)
        lines.append(f"💥 Бурных реакций в активе: {count}")

    state.clamp()
    return lines


# ---------------------------------------------------------------------------
# Рискованные выборы
# ---------------------------------------------------------------------------

def _roll_success(state: GameState, option: dict, rng: random.Random) -> bool:
    chance = option.get("chance", 0.5)
    for skill, per_level in option.get("skill_bonus", {}).items():
        chance += state.skill_levels.get(skill, 0) * per_level
    chance = min(0.95, chance)
    return rng.random() < chance


# ---------------------------------------------------------------------------
# Переходы между днями
# ---------------------------------------------------------------------------

def _complete_advance(state: GameState) -> list[str]:
    """Закончить день: усталость, отдых и переход к сцене следующего дня."""
    state.flags.pop("_pending_advance", None)
    state.day += 1
    # Сначала день выматывает, потом вечернее восстановление
    state.energy -= FATIGUE_ENERGY
    state.mood -= FATIGUE_MOOD
    state.energy = min(STAT_MAX, state.energy + REST_ENERGY)
    state.mood = min(STAT_MAX, state.mood + REST_MOOD)
    state.clamp()
    next_scene_id = DAY_SCENES.get(state.day, "finale")
    state.scene_id = next_scene_id
    if next_scene_id not in state.seen_scenes:
        state.seen_scenes.append(next_scene_id)
    return [
        (
            f"🌙 Рабочий день вымотал: энергия −{FATIGUE_ENERGY}+{REST_ENERGY}, "
            f"настроение −{FATIGUE_MOOD}+{REST_MOOD}."
        ),
        f"📅 Наступил день {state.day}.",
    ]


def _handle_next(state: GameState, next_value: str, rng: random.Random) -> list[str]:
    if next_value == "__advance__":
        # Если мы уже пережидали случайное событие — завершаем переход
        if state.flags.get("_pending_advance"):
            return _complete_advance(state)

        # Шанс на случайное событие перед концом дня
        unseen = [s for s in RANDOM_SCENES if s not in state.seen_scenes]
        pool = unseen or list(RANDOM_SCENES.keys())
        if rng.random() < RANDOM_EVENT_CHANCE:
            scene_id = rng.choice(pool)
            state.set_flag("_pending_advance", True)
            state.scene_id = scene_id
            state.seen_scenes.append(scene_id)
            return ["🎲 Непредвиденная ситуация по пути домой..."]
        return _complete_advance(state)

    # Обычный переход к конкретной сцене
    state.scene_id = next_value
    if next_value not in state.seen_scenes:
        state.seen_scenes.append(next_value)
    return []


def _check_zero_endings(state: GameState) -> str | None:
    """Мгновенные концовки при обнулении ресурсов (Telegram-режим)."""
    for resource, ending_id in ZERO_ENDING.items():
        if getattr(state, resource) <= 0:
            state.over = True
            state.ending = ending_id
            return ending_id
    return None


def _enter_exhausted(state: GameState, now_ts: int) -> None:
    """Переводим Егора в режим восстановления с таймером (VK-режим)."""
    if state.scene_id != EXHAUSTED_SCENE:
        state.exhausted_scene = state.scene_id
    state.exhausted_until = now_ts + RECOVERY_SECONDS
    state.scene_id = EXHAUSTED_SCENE
    if EXHAUSTED_SCENE not in state.seen_scenes:
        state.seen_scenes.append(EXHAUSTED_SCENE)


def _restore_from_exhaustion(state: GameState) -> None:
    """Время вышло — возвращаем ресурсы и исходную сцену."""
    state.energy = max(state.energy, RECOVERY_REFILL)
    state.mood = max(state.mood, RECOVERY_REFILL)
    state.exhausted_until = None
    state.scene_id = state.exhausted_scene or "intro"
    state.exhausted_scene = None


def tick(state: GameState, now_ts: int | None = None) -> bool:
    """Проверка таймеров при загрузке состояния. True — если восстановился."""
    now_ts = int(time.time()) if now_ts is None else now_ts
    if state.exhausted_until is not None and now_ts >= state.exhausted_until:
        _restore_from_exhaustion(state)
        return True
    return False


def grant_ad_reward(
    state: GameState, now_ts: int | None = None
) -> tuple[bool, list[str]]:
    """Награда за просмотр rewarded-ролика, с серверным кулдауном."""
    now_ts = int(time.time()) if now_ts is None else now_ts
    last_ad = int(state.flag("last_ad_at", 0))
    if now_ts - last_ad < AD_REWARD_COOLDOWN:
        wait = AD_REWARD_COOLDOWN - (now_ts - last_ad)
        return False, [f"⏳ Следующий ролик доступен через {wait} сек."]

    state.set_flag("last_ad_at", now_ts)
    was_exhausted = state.exhausted_until is not None
    state.exhausted_until = None
    if was_exhausted:
        state.scene_id = state.exhausted_scene or state.scene_id
        state.exhausted_scene = None

    state.energy = min(STAT_MAX, state.energy + AD_REWARD_ENERGY)
    state.mood = min(STAT_MAX, state.mood + AD_REWARD_MOOD)
    lines = [
        "📺 Ролик просмотрен до конца — награда получена!",
        f"⚡ Энергия +{AD_REWARD_ENERGY}, 🙂 настроение +{AD_REWARD_MOOD}",
    ]
    if was_exhausted:
        lines.append("💪 Силы вернулись — продолжаем работу!")
    return True, lines


def _resolve_zero_resources(
    state: GameState,
    permadeath: bool,
    now_ts: int,
    lines: list[str],
) -> bool:
    """Возвращает True, если игра окончена (только Telegram-режим)."""
    zero_resource = next(
        (r for r in ("energy", "mood") if getattr(state, r) <= 0), None
    )
    if zero_resource is None:
        return False

    if permadeath:
        ending_id = ZERO_ENDING[zero_resource]
        state.over = True
        state.ending = ending_id
        ending = ENDINGS[ending_id]
        lines.append(f"\n{ending['emoji']} КОНЦОВКА: {ending['title']}")
        return True

    # VK-режим: не конец игры, а пауза на восстановление
    _enter_exhausted(state, now_ts)
    resource_name = "Энергия" if zero_resource == "energy" else "Настроение"
    lines.append(
        f"\n😮‍💨 {resource_name} на нуле! Егор без сил. Отдых "
        f"{RECOVERY_SECONDS // 60} минут — или ролик, чтобы вернуться сразу."
    )
    return False


def _choose_exhausted(
    state: GameState, option_index: int, now_ts: int
) -> ChoiceResult:
    """Обработка выбора на экране восстановления."""
    scene = get_scene(state)
    if option_index != 0:
        return ChoiceResult(
            ["⛔ Сейчас доступен только отдых (или реклама)."], state, scene, False
        )
    if tick(state, now_ts):
        return ChoiceResult(
            ["💪 Отдых закончился, силы вернулись! Возвращаемся к делам."],
            state,
            get_scene(state),
            False,
        )
    remaining = max(0, int(state.exhausted_until) - now_ts)
    minutes, seconds = divmod(remaining, 60)
    return ChoiceResult(
        [
            (
                f"⏳ Егор ещё восстанавливается: осталось {minutes} мин "
                f"{seconds:02d} сек. Не хотите ждать — посмотрите ролик "
                "и вернитесь сразу."
            )
        ],
        state,
        scene,
        False,
    )


# ---------------------------------------------------------------------------
# Главная функция: выбор действия
# ---------------------------------------------------------------------------

def choose(
    state: GameState,
    option_index: int,
    rng: random.Random | None = None,
    permadeath: bool = True,
    now_ts: int | None = None,
) -> ChoiceResult:
    rng = rng or random
    now_ts = int(time.time()) if now_ts is None else now_ts

    # VK-режим: экран восстановления блокирует обычные выборы
    if state.scene_id == EXHAUSTED_SCENE:
        return _choose_exhausted(state, option_index, now_ts)

    scene = ALL_SCENES[state.scene_id]
    option = scene["options"][option_index]

    ok, reason = check_requirements(state, option.get("requires"))
    if not ok:
        return ChoiceResult([f"⛔ Недоступно: {reason}"], state, scene, False)

    lines: list[str] = []

    # Вариант с проверкой удачи
    if "success" in option or "failure" in option:
        success = _roll_success(state, option, rng)
        branch = option["success"] if success else option["failure"]
        lines.append(("✅ Успех! " if success else "❌ Провал. ") + branch["text"])
        lines.extend(_apply_effects(state, branch.get("effects", {})))
        next_value = branch.get("next", option.get("next"))
        ending_id = branch.get("ending")
    else:
        outcome = option["outcome"]
        lines.append(outcome["text"])
        lines.extend(_apply_effects(state, outcome.get("effects", {})))
        next_value = outcome.get("next", option.get("next"))
        ending_id = outcome.get("ending")

    if ending_id:
        state.over = True
        state.ending = ending_id
        ending = ENDINGS[ending_id]
        lines.append(f"\n{ending['emoji']} КОНЦОВКА: {ending['title']}")
        return ChoiceResult(lines, state, get_scene(state), True)

    if _resolve_zero_resources(state, permadeath, now_ts, lines):
        return ChoiceResult(lines, state, get_scene(state), True)
    # VK-режим: истощение прерывает цепочку — переход дня не выполняется
    if state.exhausted_until is not None:
        state.add_log(lines[0] if lines else "")
        return ChoiceResult(lines, state, get_scene(state), False)

    if next_value:
        lines.extend(_handle_next(state, next_value, rng))

    # Случайное событие тоже может обнулить ресурсы
    if _resolve_zero_resources(state, permadeath, now_ts, lines):
        return ChoiceResult(lines, state, get_scene(state), state.over)
    if state.exhausted_until is not None:
        state.add_log(lines[0] if lines else "")
        return ChoiceResult(lines, state, get_scene(state), False)

    state.add_log(lines[0] if lines else "")
    return ChoiceResult(lines, state, get_scene(state), False)


# ---------------------------------------------------------------------------
# Расходники вне сцен
# ---------------------------------------------------------------------------

def use_item(
    state: GameState,
    item_id: str,
    permadeath: bool = True,
    now_ts: int | None = None,
) -> list[str]:
    """Использовать расходный предмет из инвентаря."""
    if state.over:
        return ["Игра уже окончена. Начните новую через /newgame."]
    now_ts = int(time.time()) if now_ts is None else now_ts
    if not state.has_item(item_id):
        return ["Такого предмета нет в инвентаре."]
    if item_id not in CONSUME_EFFECTS:
        return [f"{ITEMS[item_id]['name']} нельзя использовать — это не расходник."]

    if state.charges.get(item_id, 1) <= 0 and item_id in state.charges:
        return ["Заряды закончились."]

    lines = [f"🎒 Используем: {ITEMS[item_id]['emoji']} {ITEMS[item_id]['name']}"]
    lines.extend(_apply_effects(state, CONSUME_EFFECTS[item_id]))
    _resolve_zero_resources(state, permadeath, now_ts, lines)
    return lines
