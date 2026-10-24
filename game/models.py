"""Модель состояния игрока.

Состояние — обычный dataclass, который умеет превращаться в dict и обратно.
Это позволяет хранить его где угодно: JSON-файл, Supabase, память.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Стартовые значения ресурсов
START_ENERGY = 65
START_MOOD = 65
START_AUTHORITY = 30
START_MONEY = 500

# Границы ресурсов
STAT_MIN, STAT_MAX = 0, 100

# Идентификаторы трёх навыков из ТЗ
SKILL_SEALS = "seals"          # «Каллиграфия печатей»
SKILL_GOST = "gost"            # «Скорочтение ГОСТов»
SKILL_STEALTH = "stealth"      # «Стелс-уход с совещаний»

SKILLS: dict[str, str] = {
    SKILL_SEALS: "Каллиграфия печатей",
    SKILL_GOST: "Скорочтение ГОСТов",
    SKILL_STEALTH: "Стелс-уход с совещаний",
}

SKILL_MAX_LEVEL = 5


def xp_for_next_level(level: int) -> int:
    """Сколько XP нужно, чтобы подняться с уровня ``level`` на следующий."""
    return 3 + level * 2


@dataclass
class GameState:
    """Всё состояние одной игры конкретного пользователя."""

    user_id: str
    day: int = 1
    energy: int = START_ENERGY
    mood: int = START_MOOD
    authority: int = START_AUTHORITY
    money: int = START_MONEY
    skill_levels: dict[str, int] = field(
        default_factory=lambda: {s: 0 for s in SKILLS}
    )
    skill_xp: dict[str, int] = field(default_factory=lambda: {s: 0 for s in SKILLS})
    inventory: list[str] = field(default_factory=list)
    # Расходники с количеством зарядов: {"flask": 3}
    charges: dict[str, int] = field(default_factory=dict)
    # Сюжетные флаги и счётчики (бурная реакция, визитка геологов и т.п.)
    flags: dict[str, Any] = field(default_factory=dict)
    # Какой сцена сейчас показана
    scene_id: str = "intro"
    # Уже показанные сцены (чтобы случайные не повторялись)
    seen_scenes: list[str] = field(default_factory=list)
    # Лог последних результатов выбора (для истории)
    log: list[str] = field(default_factory=list)
    # Сообщения последнего выбора — чтобы показать их после перезагрузки
    last_lines: list[str] = field(default_factory=list)
    over: bool = False
    ending: str | None = None

    # ------------------------------------------------------------------ dump/load
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameState:
        # Подставляем дефолты, чтобы старые сохранения не падали после обновлений
        defaults = cls(user_id=str(data.get("user_id", "unknown")))
        merged = defaults.to_dict()
        merged.update(data)
        merged["user_id"] = str(merged["user_id"])
        # Гарантируем наличие всех навыков
        for skill in SKILLS:
            merged["skill_levels"].setdefault(skill, 0)
            merged["skill_xp"].setdefault(skill, 0)
        return cls(**merged)

    # ------------------------------------------------------------------ helpers
    def add_log(self, line: str) -> None:
        self.log.append(line)
        # Много истории не храним — бережём место в хранилище
        if len(self.log) > 20:
            self.log = self.log[-20:]

    def clamp(self) -> None:
        """Зажимаем ресурсы в допустимые границы."""
        self.energy = max(STAT_MIN, min(STAT_MAX, self.energy))
        self.mood = max(STAT_MIN, min(STAT_MAX, self.mood))
        self.authority = max(STAT_MIN, min(STAT_MAX, self.authority))
        self.money = max(0, self.money)

    def add_xp(self, skill: str, amount: int) -> list[str]:
        """Начисляет опыт и автоматически повышает уровень. Возвращает сообщения."""
        if skill not in SKILLS or amount <= 0:
            return []
        messages: list[str] = []
        self.skill_xp[skill] += amount
        level = self.skill_levels[skill]
        while (
            level < SKILL_MAX_LEVEL
            and self.skill_xp[skill] >= xp_for_next_level(level)
        ):
            self.skill_xp[skill] -= xp_for_next_level(level)
            level += 1
            self.skill_levels[skill] = level
            messages.append(
                f"⬆️ Навык «{SKILLS[skill]}» повышен до уровня {level}!"
            )
        return messages

    def has_item(self, item_id: str) -> bool:
        return item_id in self.inventory

    def add_item(self, item_id: str) -> None:
        if item_id not in self.inventory:
            self.inventory.append(item_id)

    def remove_item(self, item_id: str) -> None:
        if item_id in self.inventory:
            self.inventory.remove(item_id)
        self.charges.pop(item_id, None)

    def flag(self, name: str, default: Any = False) -> Any:
        return self.flags.get(name, default)

    def set_flag(self, name: str, value: Any = True) -> None:
        self.flags[name] = value
