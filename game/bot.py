"""Telegram-бот «ПТОшник Егор» на aiogram 3.x.

Бот — тонкий слой: вся логика в game.engine, тексты — в game.render.
Тот же движок обслуживает веб-версию, поэтому игра в боте и в браузере
идентична.
"""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from . import engine, render
from .content import ITEMS
from .models import GameState
from .storage import Storage

logger = logging.getLogger("egor.bot")

BUTTON_TEXT_LIMIT = 60


def _short(text: str) -> str:
    return text if len(text) <= BUTTON_TEXT_LIMIT else text[: BUTTON_TEXT_LIMIT - 1] + "…"


def scene_keyboard(state: GameState, webapp_url: str | None = None) -> InlineKeyboardMarkup:
    """Кнопки под сценой: варианты выбора + расходники."""
    rows: list[list[InlineKeyboardButton]] = []

    if state.over:
        rows.append(
            [InlineKeyboardButton(text="🔄 Начать новую игру", callback_data="restart")]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    scene = engine.get_scene(state)
    for opt in engine.annotate_options(state, scene):
        if opt["available"]:
            label = opt["label"]
            if opt.get("hint"):
                label += f"  ({opt['hint']})"
            rows.append(
                [
                    InlineKeyboardButton(
                        text=_short(label), callback_data=f"choose:{opt['index']}"
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="🔒 " + _short(opt["label"]),
                        callback_data=f"locked:{opt['index']}",
                    )
                ]
            )

    # Кнопки расходников — чтобы использовать их в любой момент
    consumables = [
        iid
        for iid in state.inventory
        if ITEMS[iid].get("consumable")
        and state.charges.get(iid, 1) > 0
    ]
    if consumables:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🎒 {ITEMS[iid]['emoji']} {ITEMS[iid].get('short', ITEMS[iid]['name'])}",
                    callback_data=f"use:{iid}",
                )
                for iid in consumables
            ]
        )

    if webapp_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🕹 Открыть Mini App в браузере",
                    web_app=WebAppInfo(url=webapp_url),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


class EgorBot:
    def __init__(self, token: str, storage: Storage, webapp_url: str | None = None) -> None:
        self.bot = Bot(
            token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        self.storage = storage
        self.webapp_url = webapp_url
        self.dp = Dispatcher()
        self.router = Router()
        self.dp.include_router(self.router)
        self._register()

    # ------------------------------------------------------------------ helpers
    async def _load_or_new(self, user_id: int) -> GameState:
        state = await self.storage.load(user_id)
        if state is None:
            state = engine.new_game(user_id)
            await self.storage.save(state)
        return state

    async def _show_scene(
        self,
        message: Message,
        state: GameState,
        last_lines: list[str] | None = None,
    ) -> None:
        await message.answer(
            render.render_telegram(state, last_lines),
            reply_markup=scene_keyboard(state, self.webapp_url),
        )

    # ------------------------------------------------------------------ handlers
    def _register(self) -> None:
        r = self.router

        @r.message(CommandStart())
        async def cmd_start(message: Message) -> None:
            assert message.from_user
            state = await self._load_or_new(message.from_user.id)
            await message.answer(
                "🏗️ <b>ПТОшник Егор: Битва за Участок</b>\n\n"
                "Текстовый офисный RPG-симулятор. Выживи в бумажном аду "
                "производственно-технического отдела: следи за энергией и "
                "настроением, качай навыки, копи инвентарь и доберись до одной "
                "из пяти концовок.\n\n"
                "Команды: /newgame — заново, /state — статы, "
                "/inventory — инвентарь, /help — помощь."
            )
            await self._show_scene(message, state)

        @r.message(Command("newgame"))
        async def cmd_newgame(message: Message) -> None:
            assert message.from_user
            state = engine.new_game(message.from_user.id)
            await self.storage.save(state)
            await self._show_scene(message, state)

        @r.message(Command("help"))
        async def cmd_help(message: Message) -> None:
            await message.answer(
                "<b>Как играть</b>\n\n"
                "Каждый день — сцена с кнопками действий. Выбор меняет ресурсы:\n"
                "⚡ энергия и 🙂 настроение: упадут до нуля — конец игры;\n"
                "🎖 авторитет и навыки открывают сильные варианты в финале;\n"
                "💳 деньги тратятся в магазине Иваныча;\n"
                "🎒 расходники (фляжка, пирожок, энергетик) можно жать в любой "
                "момент кнопкой под сценой.\n\n"
                "Рискованные выборы показывают шанс и зависят от прокачки. "
                "Между днями случаются случайные события. Удачи, Егор!"
            )

        @r.message(Command("state"))
        async def cmd_state(message: Message) -> None:
            assert message.from_user
            state = await self._load_or_new(message.from_user.id)
            text = "\n".join(
                [f"<b>День {state.day}</b>", *render.stats_lines(state), "",
                 "<b>Навыки:</b>", *render.skills_lines(state)]
            )
            await message.answer(text)

        @r.message(Command("inventory"))
        async def cmd_inventory(message: Message) -> None:
            assert message.from_user
            state = await self._load_or_new(message.from_user.id)
            lines = ["<b>🎒 Инвентарь</b>", ""]
            for iid in state.inventory:
                item = ITEMS[iid]
                line = f"{item['emoji']} <b>{item['name']}</b>\n   {item['description']}"
                if iid in state.charges:
                    line += f"\n   Зарядов: {state.charges[iid]}"
                lines.append(line)
            await message.answer("\n\n".join(lines))

        @r.callback_query(F.data.startswith("choose:"))
        async def cb_choose(callback: CallbackQuery) -> None:
            assert callback.from_user and callback.message
            index = int(callback.data.split(":", 1)[1])
            state = await self._load_or_new(callback.from_user.id)
            if state.over:
                await callback.answer("Игра окончена — жмите /newgame", show_alert=True)
                return
            result = engine.choose(state, index)
            state.last_lines = result.lines
            await self.storage.save(state)
            await callback.message.edit_text(
                render.render_telegram(state, result.lines),
                reply_markup=scene_keyboard(state, self.webapp_url),
            )
            await callback.answer()

        @r.callback_query(F.data.startswith("locked:"))
        async def cb_locked(callback: CallbackQuery) -> None:
            assert callback.from_user
            index = int(callback.data.split(":", 1)[1])
            state = await self._load_or_new(callback.from_user.id)
            scene = engine.get_scene(state)
            opts = engine.annotate_options(state, scene)
            reason = opts[index]["reason"] or "Сейчас недоступно"
            await callback.answer(f"🔒 {reason}", show_alert=True)

        @r.callback_query(F.data.startswith("use:"))
        async def cb_use(callback: CallbackQuery) -> None:
            assert callback.from_user and callback.message
            item_id = callback.data.split(":", 1)[1]
            state = await self._load_or_new(callback.from_user.id)
            lines = engine.use_item(state, item_id)
            state.last_lines = lines
            await self.storage.save(state)
            await callback.message.edit_text(
                render.render_telegram(state, lines),
                reply_markup=scene_keyboard(state, self.webapp_url),
            )
            await callback.answer()

        @r.callback_query(F.data == "restart")
        async def cb_restart(callback: CallbackQuery) -> None:
            assert callback.from_user and callback.message
            state = engine.new_game(callback.from_user.id)
            await self.storage.save(state)
            await callback.message.edit_text(
                render.render_telegram(state),
                reply_markup=scene_keyboard(state, self.webapp_url),
            )
            await callback.answer("Новая игра начата!")


async def set_bot_commands(bot: Bot) -> None:
    from aiogram.types import BotCommand

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Запуск игры"),
            BotCommand(command="newgame", description="Начать заново"),
            BotCommand(command="state", description="Статы и навыки"),
            BotCommand(command="inventory", description="Инвентарь"),
            BotCommand(command="help", description="Правила"),
        ]
    )
