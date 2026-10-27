"""Страж потребления памяти: VK-контейнер должен жить на младшем тарифе Amvera.

aiogram тянет ~130 МБ RSS. В VK-сборке BOT_TOKEN не задан, поэтому бот
не импортируется вовсе — импорт game.bot остался ленивым в game.main.
Проверяем в отдельном процессе, чтобы чужие тесты не загасили sys.modules.
"""

import os
import subprocess
import sys


def test_main_without_bot_token_does_not_import_aiogram():
    env = {k: v for k, v in os.environ.items() if k != "BOT_TOKEN"}
    code = (
        "import game.main, sys;"
        "assert 'aiogram' not in sys.modules, 'aiogram загружен без BOT_TOKEN';"
        "assert 'game.bot' not in sys.modules, 'ленивый импорт бота сломан';"
        "print('footprint ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "footprint ok" in result.stdout


def test_bot_module_still_importable_for_future_telegram():
    # Сам модуль бота должен оставаться рабочим — Telegram заморожен, не удалён.
    code = "from game.bot import EgorBot, set_bot_commands; print('bot ok')"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "bot ok" in result.stdout
