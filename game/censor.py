"""Цензура текста для VK-сборки.

Правила каталога VK запрещают нецензурную лексику, поэтому весь текст перед
показом в VK прогоняется через :func:`censor_text`. Два режима:

* ``symbols``   — корень слова заменяется на ``;%:?*`` (первая буква остаётся),
                  например «долбоёб» → «д;%:?*»;
* ``euphemism`` — слово заменяется весёлым цензурным эвфемизмом
                  («чудо в каске», «каменная голова» и т.п.).

Словарь намеренно собран по корням и привязан к началу слова, чтобы не ловить
ложные срабатывания на обычных словах вроде «нёбо», «хутор», «сук» (ветка).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CENSOR_OFF = "off"
CENSOR_SYMBOLS = "symbols"
CENSOR_EUPHEMISM = "euphemism"
VALID_MODES = (CENSOR_OFF, CENSOR_SYMBOLS, CENSOR_EUPHEMISM)

# Чем заменять «тело» слова в режиме символов.
# Набор подобран так, чтобы за цензурой угадывался крепкий мат, но самого
# ругательства в тексте не было (требование правил каталога VK 1.3).
SYMBOL_GIBBERISH = "№;%:?*"


@dataclass(frozen=True)
class _Rule:
    pattern: re.Pattern[str]
    euphemism: str


# Корни привязаны к началу слова (\b + стартовые буквы), поэтому «нёбо»,
# «объём», «хутор» и ветка «сук» под правила не попадают.
_RULES: tuple[_Rule, ...] = (
    _Rule(re.compile(r"\bдолбо[её]б\w*", re.IGNORECASE), "чудо в каске"),
    _Rule(re.compile(r"\bпизд\w*", re.IGNORECASE), "сказочник"),
    _Rule(re.compile(r"\bху[йеёюяи]\w*", re.IGNORECASE), "фиговина"),
    _Rule(re.compile(r"\bбля[дт]\w*", re.IGNORECASE), "бестолочь"),
    _Rule(re.compile(r"\bсук[аиеоуы]\w*", re.IGNORECASE), "негодник"),
    _Rule(re.compile(r"\bмуд[аио]\w*", re.IGNORECASE), "каменная голова"),
    _Rule(re.compile(r"\bжоп\w*", re.IGNORECASE), "пятое место"),
    _Rule(re.compile(r"\bсран\w*", re.IGNORECASE), "безобразие"),
    _Rule(re.compile(r"\bср[ао]ть\w*", re.IGNORECASE), "безобразничать"),
    _Rule(re.compile(r"\bпохер\w*", re.IGNORECASE), "без разницы"),
    _Rule(re.compile(r"\bхерн\w*", re.IGNORECASE), "ерунда"),
)


def _symbol_replace(match: re.Match[str]) -> str:
    word = match.group(0)
    # Сохраняем регистр первой буквы, остальное — набокопорится
    first = word[0]
    return first + SYMBOL_GIBBERISH


def _euphemism_replace(rule: _Rule, match: re.Match[str]) -> str:
    word = match.group(0)
    replacement = rule.euphemism
    if word[:1].isupper():
        replacement = replacement[:1].upper() + replacement[1:]
    return replacement


def censor_text(text: str, mode: str = CENSOR_SYMBOLS) -> str:
    """Возвращает текст с цензурой. ``mode='off'`` — текст без изменений."""
    if not text or mode == CENSOR_OFF:
        return text
    if mode not in VALID_MODES:
        raise ValueError(f"Неизвестный режим цензуры: {mode!r}")

    for rule in _RULES:
        if mode == CENSOR_SYMBOLS:
            text = rule.pattern.sub(_symbol_replace, text)
        else:
            text = rule.pattern.sub(
                lambda m, r=rule: _euphemism_replace(r, m), text
            )
    return text


def censor_value(value, mode: str):
    """Рекурсивно прогоняет цензуру через строки в dict/list/кортежах."""
    if mode == CENSOR_OFF:
        return value
    if isinstance(value, str):
        return censor_text(value, mode)
    if isinstance(value, dict):
        return {k: censor_value(v, mode) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        censored = [censor_value(v, mode) for v in value]
        return type(value)(censored) if isinstance(value, tuple) else censored
    return value
