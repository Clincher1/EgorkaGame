"""Тесты модуля цензуры для VK-сборки."""

import pytest

from game.censor import (
    CENSOR_EUPHEMISM,
    CENSOR_OFF,
    CENSOR_SYMBOLS,
    censor_text,
    censor_value,
)


def test_off_mode_keeps_text():
    src = "— Егор... Ты долбоёб?"
    assert censor_text(src, CENSOR_OFF) == src


def test_symbols_mode_replaces_swear():
    out = censor_text("Ты долбоёб?", CENSOR_SYMBOLS)
    assert "долбоёб" not in out
    assert out.startswith("Ты д№;%:?*")


def test_symbols_keeps_capital():
    out = censor_text("Долбоёб явился", CENSOR_SYMBOLS)
    assert out.startswith("Д№;%:?*")


def test_euphemism_mode():
    out = censor_text("Ты долбоёб?", CENSOR_EUPHEMISM)
    assert "долбоёб" not in out.lower()
    assert "чудо в каске" in out


def test_euphemism_capitalized():
    out = censor_text("Долбоёб пришёл", CENSOR_EUPHEMISM)
    assert "Чудо в каске" in out


def test_word_forms_caught():
    for word in ("долбоёба", "долбоёбы", "долбоеб"):
        out = censor_text(word, CENSOR_SYMBOLS)
        assert "долб" not in out.lower()


@pytest.mark.parametrize(
    "clean",
    [
        "Кофе обжигает нёбо",
        "Хутор за стройкой",
        "Сук дерева упал на забор",
        "Объём работ большой",
        "Блин, опять совещание",
        "Сукно на столе протёрлось",
    ],
)
def test_clean_words_not_touched(clean):
    assert censor_text(clean, CENSOR_SYMBOLS) == clean
    assert censor_text(clean, CENSOR_EUPHEMISM) == clean


def test_multiple_swear_words_in_one_text():
    out = censor_text("долбоёб и мудак", CENSOR_SYMBOLS)
    assert "м№;%:?*" in out and "д№;%:?*" in out


def test_censor_value_recursive():
    data = {
        "text": "Ты долбоёб",
        "nested": ["мудак", 42, {"ok": "нёбо"}],
    }
    out = censor_value(data, CENSOR_SYMBOLS)
    assert isinstance(out["nested"][1], int)
    assert "долбоёб" not in out["text"]
    assert "мудак" not in out["nested"][0]
    assert out["nested"][2]["ok"] == "нёбо"


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        censor_text("текст", "hardcore")


def test_empty_and_none_safe():
    assert censor_text("", CENSOR_SYMBOLS) == ""
    assert censor_value(None, CENSOR_SYMBOLS) is None
