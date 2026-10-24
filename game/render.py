"""Подготовка состояния к показу в боте и на вебе.

Здесь нет ни Telegram, ни HTML — только структурированные данные и текст,
поэтому модуль одинаково используется обоими клиентами.
"""

from __future__ import annotations

from . import engine
from .content import ITEMS
from .models import SKILLS, STAT_MAX, GameState


def _bar(value: int, width: int = 10) -> str:
    filled = round(max(0, min(STAT_MAX, value)) / STAT_MAX * width)
    return "▰" * filled + "▱" * (width - filled)


def stats_lines(state: GameState) -> list[str]:
    return [
        f"⚡ Энергия:    {_bar(state.energy)} {state.energy}",
        f"🙂 Настроение: {_bar(state.mood)} {state.mood}",
        f"🎖 Авторитет:  {_bar(state.authority)} {state.authority}",
        f"💳 Деньги:     {state.money} ₽",
    ]


def skills_lines(state: GameState) -> list[str]:
    lines = []
    for skill_id, title in SKILLS.items():
        level = state.skill_levels[skill_id]
        stars = "⭐" * level + "☆" * (5 - level)
        lines.append(f"{stars} {title} (ур. {level})")
    return lines


def inventory_lines(state: GameState) -> list[str]:
    if not state.inventory:
        return ["🎒 Инвентарь пуст"]
    lines = []
    for item_id in state.inventory:
        item = ITEMS[item_id]
        line = f"{item['emoji']} {item['name']}"
        if item_id in state.charges:
            line += f" — зарядов: {state.charges[item_id]}"
        if item.get("consumable"):
            line += " [используемо]"
        lines.append(line)
    return lines


def render_view(state: GameState) -> dict:
    """Полное состояние для веб-клиента (JSON)."""
    scene = engine.get_scene(state)
    options = (
        engine.annotate_options(state, scene)
        if not state.over
        else []
    )
    return {
        "day": state.day,
        "over": state.over,
        "ending": state.ending,
        "scene": {
            "id": scene["id"],
            "emoji": scene.get("emoji", "📄"),
            "title": scene["title"],
            "text": scene["text"],
        },
        "options": options,
        "stats": {
            "energy": state.energy,
            "mood": state.mood,
            "authority": state.authority,
            "money": state.money,
        },
        "skills": [
            {"id": sid, "title": title, "level": state.skill_levels[sid]}
            for sid, title in SKILLS.items()
        ],
        "inventory": [
            {
                "id": iid,
                "name": ITEMS[iid]["name"],
                "emoji": ITEMS[iid]["emoji"],
                "consumable": ITEMS[iid].get("consumable", False),
                "charges": state.charges.get(iid),
            }
            for iid in state.inventory
        ],
        "flags": {"absurd_count": state.flag("absurd_count", 0)},
    }


def render_telegram(state: GameState, last_lines: list[str] | None = None) -> str:
    """Текст сообщения для Telegram (HTML-разметка aiogram отключит экранирование)."""
    scene = engine.get_scene(state)
    parts = [
        f"<b>{scene.get('emoji', '📄')} {scene['title']}</b>  <i>(день {state.day})</i>",
        "",
        scene["text"],
    ]

    if last_lines:
        parts.extend(["", "<b>Что произошло:</b>"])
        parts.extend(f"• {line}" for line in last_lines)

    parts.extend(["", "—" * 18, *stats_lines(state)])
    parts.extend(["", "<b>Навыки:</b>", *skills_lines(state)])
    parts.extend(["", "<b>Инвентарь:</b>", *inventory_lines(state)])

    if state.over:
        parts.extend(["", "💀 Игра окончена. Команда /newgame — начать заново."])
    else:
        parts.extend(["", "Выберите действие кнопками ниже 👇"])
    return "\n".join(parts)
