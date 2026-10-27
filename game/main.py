"""Точка входа: один процесс = веб-версия + Telegram-бот.

Режимы бота (BOT_MODE):
  polling  — long polling, удобно локально и на VPS;
  webhook  — Telegram сам стучится на WEBHOOK_URL/tg/webhook, удобно на
             бесплатных хостингах, которые засыпают (Render и т.п.).

Без BOT_TOKEN работает только веб-версия — можно играть в браузере.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from aiohttp import web

from .config import load_config
from .storage import SupabaseStorage, build_storage
from .webapp import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("egor.main")


async def main() -> None:
    config = load_config()
    storage = build_storage()

    bot = dp = None
    webapp_url = os.getenv("WEBAPP_URL") or config.webhook_url
    if config.bot_enabled:
        # Ленивый импорт: aiogram тянет ~130 МБ RSS, а в VK-сборке бот
        # не нужен (BOT_TOKEN не задан) — контейнер укладывается в младший тариф.
        from .bot import EgorBot, set_bot_commands

        egor_bot = EgorBot(config.bot_token, storage, webapp_url)  # type: ignore[arg-type]
        bot = egor_bot.bot
        dp = egor_bot.dp
        await set_bot_commands(bot)
        logger.info("Telegram-бот включён (режим: %s)", config.bot_mode)
    else:
        logger.info("BOT_TOKEN не задан — работает только веб-версия")

    app = create_app(config, storage, bot=bot, dp=dp)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.web_host, config.web_port)
    await site.start()
    logger.info("Веб-сервер поднят на http://%s:%s", config.web_host, config.web_port)
    if config.vk_app_id:
        logger.info(
            "VK Mini App: app_id=%s, защищённый ключ задан=%s (длина %s)",
            config.vk_app_id,
            bool(config.vk_secret),
            len(config.vk_secret) if config.vk_secret else 0,
        )
    else:
        logger.info("VK Mini App: VK_APP_ID не задан — VK-авторизация отключена")

    polling_task: asyncio.Task | None = None
    if bot is not None and dp is not None:
        if config.bot_mode == "webhook" and config.webhook_url:
            url = config.webhook_url.rstrip("/") + "/tg/webhook"
            await bot.set_webhook(url, drop_pending_updates=True)
            logger.info("Webhook установлен: %s", url)
        else:
            polling_task = asyncio.create_task(
                dp.start_polling(bot, handle_signals=False)
            )

            def _polling_died(task: asyncio.Task) -> None:
                if task.exception():
                    logger.exception("Polling упал: %s", task.exception())

            polling_task.add_done_callback(_polling_died)
            logger.info("Long polling запущен")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # Windows
            pass

    try:
        await stop_event.wait()
    finally:
        logger.info("Останавливаемся...")
        if polling_task:
            polling_task.cancel()
        if bot is not None:
            await bot.delete_webhook(drop_pending_updates=True)
            await bot.session.close()
        if isinstance(storage, SupabaseStorage):
            await storage.close()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
