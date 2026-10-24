"""Конфигурация приложения из переменных окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    bot_token: str | None
    # polling | webhook — режим работы Telegram-бота
    bot_mode: str
    # Публичный HTTPS-адрес для webhook (например https://egor.onrender.com)
    webhook_url: str | None
    web_host: str
    web_port: int
    # Секрет для проверки данных Telegram Mini App; по умолчанию = токен бота
    secret: str | None

    @property
    def bot_enabled(self) -> bool:
        return bool(self.bot_token)


def load_config() -> Config:
    return Config(
        bot_token=os.getenv("BOT_TOKEN") or None,
        bot_mode=os.getenv("BOT_MODE", "polling").lower(),
        webhook_url=os.getenv("WEBHOOK_URL") or None,
        web_host=os.getenv("WEB_HOST", "0.0.0.0"),
        web_port=int(os.getenv("PORT", os.getenv("WEB_PORT", "8080"))),
        secret=os.getenv("WEBAPP_SECRET") or os.getenv("BOT_TOKEN") or None,
    )
