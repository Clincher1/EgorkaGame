"""Тесты VK-механики: истощение по таймеру и награда за рекламу."""

from game import engine
from game.engine import (
    AD_REWARD_COOLDOWN,
    RECOVERY_REFILL,
    RECOVERY_SECONDS,
)

NOW = 1_000_000


class _FailRng:
    """RNG, у которого все рискованные выборы проваливаются."""

    def random(self):
        return 0.99

    def choice(self, seq):
        return seq[0]


def _state_at_day1_with_energy(energy: int, mood: int = 60):
    state = engine.new_game("vk-1")
    engine.choose(state, 0)  # intro -> день 1
    state.energy = energy
    state.mood = mood
    return state


def test_permadeath_mode_keeps_old_behavior():
    state = _state_at_day1_with_energy(5)
    result = engine.choose(state, 0, rng=_FailRng(), permadeath=True, now_ts=NOW)
    assert result.ended
    assert state.over is True
    assert state.ending == "tragedy"
    assert state.exhausted_until is None


def test_vk_mode_enters_exhausted_instead_of_game_over():
    state = _state_at_day1_with_energy(5)
    result = engine.choose(
        state, 0, rng=_FailRng(), permadeath=False, now_ts=NOW
    )
    assert result.ended is False
    assert state.over is False
    assert state.ending is None
    assert state.scene_id == "exhausted_rest"
    assert state.exhausted_until == NOW + RECOVERY_SECONDS
    # запомнили сцену, куда вернуть игрока
    assert state.exhausted_scene == "day1_act"


def test_exhausted_blocks_normal_choices():
    state = _state_at_day1_with_energy(5)
    engine.choose(state, 0, rng=_FailRng(), permadeath=False, now_ts=NOW)
    # любой вариант, кроме нулевого, отклоняется
    result = engine.choose(state, 5, permadeath=False, now_ts=NOW + 10)
    assert state.scene_id == "exhausted_rest"
    assert "только отдых" in result.lines[0]


def test_rest_before_timer_shows_countdown():
    state = _state_at_day1_with_energy(5)
    engine.choose(state, 0, rng=_FailRng(), permadeath=False, now_ts=NOW)
    result = engine.choose(state, 0, permadeath=False, now_ts=NOW + 60)
    assert state.scene_id == "exhausted_rest"
    assert any("осталось" in line for line in result.lines)


def test_tick_restores_after_timer():
    state = _state_at_day1_with_energy(5)
    engine.choose(state, 0, rng=_FailRng(), permadeath=False, now_ts=NOW)
    # время ещё не вышло
    assert engine.tick(state, NOW + 100) is False
    assert state.scene_id == "exhausted_rest"
    # время вышло — силы и сцена вернулись
    assert engine.tick(state, NOW + RECOVERY_SECONDS) is True
    assert state.exhausted_until is None
    assert state.scene_id == "day1_act"
    assert state.energy >= RECOVERY_REFILL
    assert state.mood >= RECOVERY_REFILL


def test_ad_reward_clears_exhaustion_immediately():
    state = _state_at_day1_with_energy(5)
    engine.choose(state, 0, rng=_FailRng(), permadeath=False, now_ts=NOW)
    ok, lines = engine.grant_ad_reward(state, now_ts=NOW + 30)
    assert ok is True
    assert state.exhausted_until is None
    assert state.scene_id == "day1_act"
    assert state.energy > 5
    assert any("Ролик просмотрен" in line for line in lines)


def test_ad_reward_cooldown_prevents_abuse():
    state = engine.new_game("vk-2")
    ok, _ = engine.grant_ad_reward(state, now_ts=NOW)
    assert ok is True
    energy_after_first = state.energy
    ok2, lines = engine.grant_ad_reward(state, now_ts=NOW + AD_REWARD_COOLDOWN - 1)
    assert ok2 is False
    assert state.energy == energy_after_first
    assert any("доступен через" in line for line in lines)
    # после кулдауна снова можно
    ok3, _ = engine.grant_ad_reward(state, now_ts=NOW + AD_REWARD_COOLDOWN + 1)
    assert ok3 is True


def test_ad_reward_works_without_exhaustion():
    state = engine.new_game("vk-3")
    ok, _ = engine.grant_ad_reward(state, now_ts=NOW)
    assert ok is True
    assert state.energy == 100  # 65 стартовых + 35 награды


def test_mood_exhaustion_uses_same_flow():
    state = _state_at_day1_with_energy(60, mood=2)
    # вариант 2 в day1 — Женя, настроение -5
    engine.choose(state, 2, permadeath=False, now_ts=NOW)
    assert state.over is False
    assert state.scene_id == "exhausted_rest"
    assert state.exhausted_until is not None


def test_state_roundtrip_keeps_exhaustion_fields():
    from game.models import GameState

    state = _state_at_day1_with_energy(5)
    engine.choose(state, 0, rng=_FailRng(), permadeath=False, now_ts=NOW)
    restored = GameState.from_dict(state.to_dict())
    assert restored.exhausted_until == state.exhausted_until
    assert restored.exhausted_scene == "day1_act"
    assert restored.scene_id == "exhausted_rest"
