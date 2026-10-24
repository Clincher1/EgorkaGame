"""Игровой движок: применяет выбор игрока к состоянию.

Движок ничего не знает про Telegram и HTTP — только данные и правила.
Поэтому он полностью покрывается юнит-тестами и используется и ботом,
и веб-версией.
"""

from __future__ import annotations

import random
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
    """Мгновенные концовки при обнулении ресурсов."""
    for resource, ending_id in ZERO_ENDING.items():
        if getattr(state, resource) <= 0:
            state.over = True
            state.ending = ending_id
            return ending_id
    return None


# ---------------------------------------------------------------------------
# Главная функция: выбор действия
# ---------------------------------------------------------------------------

def choose(
    state: GameState,
    option_index: int,
    rng: random.Random | None = None,
) -> ChoiceResult:
    rng = rng or random
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

    zero_ending = _check_zero_endings(state)
    if zero_ending:
        ending = ENDINGS[zero_ending]
        lines.append(f"\n{ending['emoji']} КОНЦОВКА: {ending['title']}")
        return ChoiceResult(lines, state, get_scene(state), True)

    if next_value:
        lines.extend(_handle_next(state, next_value, rng))

    # Случайное событие тоже может обнулить ресурсы
    zero_ending = _check_zero_endings(state)
    if zero_ending:
        ending = ENDINGS[zero_ending]
        lines.append(f"\n{ending['emoji']} КОНЦОВКА: {ending['title']}")
        return ChoiceResult(lines, state, get_scene(state), True)

    state.add_log(lines[0] if lines else "")
    return ChoiceResult(lines, state, get_scene(state), False)


# ---------------------------------------------------------------------------
# Расходники вне сцен
# ---------------------------------------------------------------------------

def use_item(state: GameState, item_id: str) -> list[str]:
    """Использовать расходный предмет из инвентаря."""
    if state.over:
        return ["Игра уже окончена. Начните новую через /newgame."]
    if not state.has_item(item_id):
        return ["Такого предмета нет в инвентаре."]
    if item_id not in CONSUME_EFFECTS:
        return [f"{ITEMS[item_id]['name']} нельзя использовать — это не расходник."]

    if state.charges.get(item_id, 1) <= 0 and item_id in state.charges:
        return ["Заряды закончились."]

    lines = [f"🎒 Используем: {ITEMS[item_id]['emoji']} {ITEMS[item_id]['name']}"]
    lines.extend(_apply_effects(state, CONSUME_EFFECTS[item_id]))
    _check_zero_endings(state)
    return lines
