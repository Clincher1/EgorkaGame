"""Тесты Telegram-клавиатур и проверки подписи Mini App."""

import hashlib
import hmac
from urllib.parse import urlencode

from game import engine
from game.bot import scene_keyboard
from game.webapp import verify_init_data


def test_scene_keyboard_contains_all_options():
    state = engine.new_game(1)
    engine.choose(state, 0)
    state.scene_id = "day2_stamp"
    kb = scene_keyboard(state)
    # три варианта сцены
    callback_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "choose:0" in callback_data
    assert "choose:1" in callback_data
    # фляжка с зарядами — заблокированной не выглядит
    assert "choose:2" in callback_data


def test_locked_option_has_lock_prefix():
    state = engine.new_game(1)
    engine.choose(state, 0)
    state.scene_id = "day9_shop"
    state.money = 0  # ничего нельзя купить
    kb = scene_keyboard(state)
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any(t.startswith("🔒") for t in texts)


def test_game_over_keyboard_offers_restart():
    state = engine.new_game(1)
    state.over = True
    state.ending = "legend"
    kb = scene_keyboard(state)
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(buttons) == 1
    assert buttons[0].callback_data == "restart"


def test_verify_init_data_valid_and_tampered():
    token = "123456:TEST_FAKE_TOKEN"
    fields = {
        "auth_date": "1700000000",
        "query_id": "abc",
        "user": '{"id": 555, "first_name": "Егор"}',
    }
    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(fields.items())
    )
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    valid_hash = hmac.new(
        secret, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    init_data = urlencode({**fields, "hash": valid_hash})
    user = verify_init_data(init_data, token)
    assert user == {"id": 555, "first_name": "Егор"}

    # подделка данных под тем же hash должна отклоняться
    tampered = init_data.replace("555", "777")
    assert verify_init_data(tampered, token) is None
    # неверный токен
    assert verify_init_data(init_data, "wrong:token") is None
    # мусор
    assert verify_init_data("совсем не данные", token) is None
