"""Тесты игрового движка и контента."""

import random

import pytest

from game import content, engine
from game.content import (
    CONSUME_EFFECTS,
    DAY_SCENES,
    ENDINGS,
    ITEMS,
    RANDOM_SCENES,
    SCENES,
)
from game.models import (
    SKILL_GOST,
    SKILL_SEALS,
    SKILL_STEALTH,
    SKILLS,
    GameState,
    xp_for_next_level,
)

# ---------------------------------------------------------------------------
# Базовое состояние
# ---------------------------------------------------------------------------

def test_new_game_defaults():
    state = engine.new_game(42)
    assert state.user_id == "42"
    assert state.day == 1
    assert state.energy == 65
    assert state.mood == 65
    assert state.authority == 30
    assert state.scene_id == "intro"
    assert state.has_item("mk52")
    assert state.has_item("red_pen")
    assert state.has_item("flask")
    assert state.charges["flask"] == 3
    assert not state.over


def test_state_roundtrip():
    state = engine.new_game(7)
    state.energy = 42
    state.set_flag("taiga", True)
    restored = GameState.from_dict(state.to_dict())
    assert restored.to_dict() == state.to_dict()


# ---------------------------------------------------------------------------
# Выборы и эффекты
# ---------------------------------------------------------------------------

def test_intro_moves_to_day1():
    state = engine.new_game(1)
    result = engine.choose(state, 0)
    assert state.scene_id == "day1_act"
    assert not result.ended
    assert "day1_act" in state.seen_scenes


class _NoEventRng(random.Random):
    """RNG, при котором случайные события не выпадают."""

    def random(self):
        return 1.0


def test_deterministic_choice_effects():
    state = engine.new_game(1)
    engine.choose(state, 0)  # intro -> day1
    # вариант 1: переписать по образцу — энергия -5, затем усталость и отдых
    result = engine.choose(state, 1, rng=_NoEventRng())
    # 65 - 5 (сцена) - 10 (усталость) + 8 (отдых)
    assert state.energy == 58
    # 65 - 8 (усталость) + 5 (отдых)
    assert state.mood == 62
    # 4 XP = сразу 1-й уровень «Скорочтения ГОСТов»
    assert state.skill_levels[SKILL_GOST] == 1
    assert state.scene_id == "day2_stamp"
    assert result.scene["id"] == engine.get_scene(state)["id"]


def test_risky_choice_success_and_failure():
    # rng, всегда проваливающий / всегда успешный
    class FailRng:
        def random(self):
            return 0.99
        def choice(self, seq):
            return seq[0]

    class WinRng:
        def random(self):
            return 0.01
        def choice(self, seq):
            return seq[0]

    fail_state = engine.new_game(1)
    engine.choose(fail_state, 0)
    r = engine.choose(fail_state, 0, rng=FailRng())  # бурная реакция, провал
    assert any("Провал" in line for line in r.lines)
    assert fail_state.authority < 30
    assert fail_state.flag("absurd_count") == 1

    win_state = engine.new_game(1)
    engine.choose(win_state, 0)
    r = engine.choose(win_state, 0, rng=WinRng())
    assert any("Успех" in line for line in r.lines)
    assert win_state.authority > 30


def test_skill_level_up():
    state = engine.new_game(1)
    messages = state.add_xp(SKILL_SEALS, xp_for_next_level(0))
    assert state.skill_levels[SKILL_SEALS] == 1
    assert any("повышен до уровня 1" in m for m in messages)
    # потолок уровней
    state.skill_levels[SKILL_SEALS] = 5
    state.skill_xp[SKILL_SEALS] = 0
    state.add_xp(SKILL_SEALS, 999)
    assert state.skill_levels[SKILL_SEALS] == 5


def test_requirements_block_and_unlock():
    state = engine.new_game(1)
    engine.choose(state, 0)
    state.scene_id = "day2_stamp"
    # подкуп фляжкой требует заряд
    state.charges["flask"] = 0
    ok, reason = engine.check_requirements(
        state, {"charge": "flask"}
    )
    assert not ok and reason
    state.charges["flask"] = 2
    ok, _ = engine.check_requirements(state, {"charge": "flask"})
    assert ok
    # деньги
    state.money = 10
    ok, reason = engine.check_requirements(state, {"money": 300})
    assert not ok and "300" in reason
    # навык
    state.skill_levels[SKILL_STEALTH] = 1
    ok, _ = engine.check_requirements(state, {"skill": (SKILL_STEALTH, 2)})
    assert not ok
    state.skill_levels[SKILL_STEALTH] = 2
    ok, _ = engine.check_requirements(state, {"skill": (SKILL_STEALTH, 2)})
    assert ok


def test_locked_choice_is_rejected():
    state = engine.new_game(1)
    engine.choose(state, 0)
    state.scene_id = "day2_stamp"
    state.charges["flask"] = 0
    result = engine.choose(state, 2)  # подкуп без зарядов
    assert state.scene_id == "day2_stamp"
    assert any("Недоступно" in line for line in result.lines)


def test_use_consumable_flask():
    state = engine.new_game(1)
    energy_before = state.energy
    lines = engine.use_item(state, "flask")
    assert state.energy > energy_before
    assert state.charges["flask"] == 2
    assert any("Используем" in line for line in lines)
    # не-расходник использовать нельзя
    assert "нельзя использовать" in engine.use_item(state, "mk52")[0]


def test_use_pie_removes_item():
    state = engine.new_game(1)
    state.add_item("svetlana_pie")
    engine.use_item(state, "svetlana_pie")
    assert not state.has_item("svetlana_pie")


# ---------------------------------------------------------------------------
# Дни, отдых, случайные события
# ---------------------------------------------------------------------------

class _Rng(random.Random):
    """RNG с управляемым вызовом choice для случайных сцен."""


def test_advance_day_rests_and_increments():
    state = engine.new_game(1)
    engine.choose(state, 0)
    state.energy, state.mood = 30, 30
    # rng без случайных событий: random() всегда 1 -> шанс события провален
    rng = random.Random(0)
    rng.random = lambda: 1.0  # type: ignore[method-assign]
    rng.choice = lambda seq: seq[0]  # type: ignore[method-assign]
    engine.choose(state, 1, rng=rng)  # вариант с next=__advance__
    assert state.day == 2
    assert state.scene_id == "day2_stamp"
    assert state.energy == 23  # 30 - 5 (сцена) - 10 (усталость) + 8 (отдых)
    assert state.mood == 27    # 30 - 8 (усталость) + 5 (отдых)


def test_random_event_then_advance():
    state = engine.new_game(1)
    engine.choose(state, 0)
    rng = random.Random(0)
    rng.random = lambda: 0.0  # type: ignore[method-assign] -> событие будет
    rng.choice = lambda seq: "r_coffee"  # type: ignore[method-assign]
    engine.choose(state, 1, rng=rng)
    assert state.flags.get("_pending_advance") is True
    assert state.scene_id == "r_coffee"
    # второй выбор завершает переход на новый день
    rng2 = random.Random(1)
    rng2.random = lambda: 1.0  # type: ignore[method-assign]
    engine.choose(state, 1, rng=rng2)  # вода из кулера
    assert state.day == 2
    assert state.flags.get("_pending_advance") is None


# ---------------------------------------------------------------------------
# Концовки
# ---------------------------------------------------------------------------

def test_zero_energy_tragedy():
    state = engine.new_game(1)
    state.energy = 5
    state.scene_id = "day1_act"
    state.flags["absurd_count"] = 0
    # провальный вариант с потерей энергии
    class FailRng:
        def random(self):
            return 0.99
        def choice(self, seq):
            return seq[0]
    result = engine.choose(state, 0, rng=FailRng())
    assert result.ended
    assert state.over
    assert state.ending == "tragedy"


def test_zero_mood_metro():
    state = engine.new_game(1)
    state.mood = 2
    state.scene_id = "day4_svetlana"
    engine.choose(state, 2)  # промямлить и убежать: mood -12
    assert state.over
    assert state.ending == "metro"


def _jump_to_finale(state: GameState) -> None:
    state.day = 10
    state.scene_id = "finale"


def test_finale_hero_ending():
    state = engine.new_game(1)
    _jump_to_finale(state)
    state.authority = 75
    state.skill_levels = {SKILL_SEALS: 2, SKILL_GOST: 2, SKILL_STEALTH: 2}
    result = engine.choose(state, 0)
    assert result.ended and state.ending == "hero"


def test_finale_taiga_requires_card():
    state = engine.new_game(1)
    _jump_to_finale(state)
    result = engine.choose(state, 1)  # нет визитки
    assert not result.ended
    state.add_item("business_card")
    result = engine.choose(state, 1)
    assert result.ended and state.ending == "taiga"


def test_finale_legend_always_available():
    state = engine.new_game(1)
    _jump_to_finale(state)
    result = engine.choose(state, 2)
    assert result.ended and state.ending == "legend"
    assert state.flag("absurd_count") >= 1


def test_finale_metro_fallback():
    state = engine.new_game(1)
    _jump_to_finale(state)
    result = engine.choose(state, 3)
    assert result.ended and state.ending == "metro"


def test_full_playthrough_to_finale():
    """Проходим все 9 дней, выбирая первый доступный вариант, до финала."""
    state = engine.new_game(1)
    rng = random.Random(31337)
    steps = 0
    while not state.over and state.day < 10:
        scene = engine.get_scene(state)
        options = engine.annotate_options(state, scene)
        available = [o["index"] for o in options if o["available"]]
        assert available, f"Нет доступных вариантов в сцене {scene['id']}"
        engine.choose(state, available[0], rng=rng)
        steps += 1
        assert steps < 200, "Зацикливание сюжета"
    assert state.day == 10
    assert state.scene_id == "finale"


# ---------------------------------------------------------------------------
# Целостность контента
# ---------------------------------------------------------------------------

ALL_SCENES = {**SCENES, **RANDOM_SCENES}


def test_all_scene_links_resolve():
    for scene_id, scene in ALL_SCENES.items():
        for i, option in enumerate(scene["options"]):
            targets = [option]
            if "success" in option:
                targets += [option["success"], option["failure"]]
            for target in targets:
                nxt = target.get("next", option.get("next"))
                if nxt and nxt != "__advance__":
                    assert nxt in ALL_SCENES, f"{scene_id}[{i}] -> {nxt}"
                if target.get("ending"):
                    assert target["ending"] in ENDINGS


def test_all_items_and_skills_exist():
    for scene_id, scene in ALL_SCENES.items():
        for option in scene["options"]:
            req = option.get("requires") or {}
            for key in ("item", "no_item", "charge"):
                if key in req:
                    assert req[key] in ITEMS, f"{scene_id}: неизвестный предмет {req[key]}"
            if "skill" in req:
                assert req["skill"][0] in SKILLS
            effects = option.get("outcome", option.get("success", {})).get("effects", {})
            for item_id in effects.get("add_item", []) if isinstance(
                effects.get("add_item"), list
            ) else ([effects["add_item"]] if effects.get("add_item") else []):
                assert item_id in ITEMS
            for skill in effects.get("xp", {}):
                assert skill in SKILLS


def test_consumables_have_effects():
    for item_id, item in ITEMS.items():
        if item.get("consumable"):
            assert item_id in CONSUME_EFFECTS, f"{item_id} — расходник без эффектов"


def test_day_scenes_and_endings_complete():
    for day, scene_id in DAY_SCENES.items():
        assert scene_id in SCENES
        assert SCENES[scene_id].get("day") == day
    assert set(ENDINGS) == {"tragedy", "metro", "hero", "taiga", "legend"}


def test_every_scene_has_options():
    for scene_id, scene in ALL_SCENES.items():
        assert scene["options"], f"Сцена {scene_id} без вариантов"
        for option in scene["options"]:
            assert "label" in option
            assert "outcome" in option or ("success" in option and "failure" in option)


def test_greedy_playthrough_survives_to_finale():
    """Аккуратный игрок (выбор с лучшими видимыми эффектами) должен доживать до финала."""

    def score_option(scene, index):
        opt = scene["options"][index]
        effects = opt.get("outcome", opt.get("success", {})).get("effects", {})
        return (
            effects.get("authority", 0)
            + sum(effects.get("xp", {}).values())
            + effects.get("mood", 0)
            + effects.get("energy", 0)
        )

    for seed in range(15):
        rng = random.Random(seed)
        state = engine.new_game(f"greedy-{seed}")
        steps = 0
        while not state.over and state.day < 10:
            scene = engine.get_scene(state)
            available = [
                o["index"] for o in engine.annotate_options(state, scene) if o["available"]
            ]
            best = max(available, key=lambda i: score_option(scene, i))
            engine.choose(state, best, rng=rng)
            steps += 1
            assert steps < 200
        assert state.day == 10, f"seed {seed}: аккуратный игрок не дожил до финала"


def test_render_works_for_every_scene():
    from game import render

    for scene_id in content.ALL_SCENES:
        state = engine.new_game("render")
        state.scene_id = scene_id
        text = render.render_telegram(state)  # не должно бросать исключений
        assert "Энергия" in text and "Навыки" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
