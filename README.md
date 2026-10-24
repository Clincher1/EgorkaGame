# 🏗️ ПТОшник Егор: Битва за Участок

Текстовый RPG-симулятор офисного выживания в стиле старой школы:
абсурдный юмор, постсоветская романтика бумажного ада и лёгкий стресс
от начальства. Егор — бывший электрик из метро, попавший в ПТО
строительной компании. Ему нужно пережить 10 рабочих дней, не потеряв
энергию и настроение, прокачать навыки и добраться до одной из пяти концовок.

Игра работает **одновременно** как:

- 🤖 **Telegram-бот** на [aiogram 3.x](https://aiogram.dev/) — кнопки-действия прямо в чате;
- 🌐 **браузерная игра** и **Telegram Mini App** — ретро-терминал на ванильном JS;
- 🧩 переиспользуемое **ядро на чистом Python**, покрытое тестами.

Один процесс, один бесплатный деплой, ноль обязательных внешних сервисов.

## 🎮 Механики

| Механика | Реализация |
|---|---|
| ⚡ Энергия / 🙂 Настроение | Падают до нуля — мгновенная концовка (увольнение) |
| 🎖 Авторитет | Открывает сильные варианты в финале |
| ⭐ Навыки | «Каллиграфия печатей», «Скорочтение ГОСТов», «Стелс-уход с совещаний» — 5 уровней, растут от выборов |
| 🎒 Инвентарь | МК-52, красная ручка, фляжка с «чайком» (заряды), пирожок Светланы, левая печать и др. |
| 💳 Деньги | Магазин Иваныча на 9-й день: печати, СНиП, справки, энергетик |
| 🎲 Риск | Часть выборов имеет шанс успеха, бонус зависит от прокачки |
| 🎲 Случайные события | Кофе-машина, восстание принтера, геологи в курилке и т.д. |
| 🎬 Концовки | «Герой ПТО», «Бегство в геологи», «Легенда о бурной реакции», «Обратно в метро», «Трагедия» |

## 🗂 Структура проекта

```
game/
  models.py    — состояние игрока (dataclass + сериализация)
  content.py   — ВЕСЬ сюжет: сцены, предметы, навыки, концовки
  engine.py    — правила: эффекты, риски, прокачка, смена дней, концовки
  storage.py   — сохранения: JSON-файлы или Supabase (PostgREST)
  render.py    — подготовка данных для бота и веба
  bot.py       — Telegram-бот aiogram 3 (роутеры, inline-кнопки)
  webapp.py    — aiohttp: REST API, статика, webhook, проверка подписи Mini App
  config.py    — конфиг из переменных окружения
  main.py      — точка входа: веб + бот в одном процессе
web/           — фронтенд без сборки (HTML/CSS/JS)
tests/         — pytest: движок, хранилище, клавиатуры, подпись Mini App
```

## 🚀 Локальный запуск

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Только браузерная версия (без токена):
python -m game.main
# → http://localhost:8080
```

С ботом:

```bash
cp .env.example .env               # вписать BOT_TOKEN от @BotFather
export $(grep -v '^#' .env | xargs)
python -m game.main
```

Режим `BOT_MODE=polling` подходит для локали и VPS: бот сам забирает
обновления. Режим `webhook` нужен хостингам, которые засыпают
(Render Free и т.п.) — Telegram сам будит сервис запросом на `/tg/webhook`.

## 🧪 Тесты

```bash
pip install -r requirements-dev.txt
pytest -q
ruff check game/ tests/
```

## ☁️ Деплой (всё бесплатно)

### Вариант A. Render.com + webhook (рекомендуется)

1. Залейте репозиторий на GitHub.
2. На [render.com](https://render.com): **New + → Blueprint**, выберите репозиторий —
   подхватится `render.yaml`.
3. В переменных окружения укажите:
   - `BOT_TOKEN` — токен BotFather;
   - `WEBHOOK_URL` — `https://<имя-сервиса>.onrender.com`;
   - `WEBAPP_URL` — тот же адрес (для кнопки Mini App);
   - при желании `SUPABASE_URL` / `SUPABASE_KEY`.
4. Готово: бот в webhook-режиме, браузерная игра на том же домене,
   health-check `/healthz`.

### Вариант B. Любой VPS / домашний сервер

```bash
docker build -t egor-game .
docker run -d -p 8080:8080 \
  -e BOT_TOKEN=xxx -e BOT_MODE=polling \
  egor-game
```

### Вариант C. Hugging Face Spaces (Docker SDK)

Скопируйте `Dockerfile` и код в Space с типом **Docker**: веб-версия
поднимется сразу, для бота добавьте секреты `BOT_TOKEN` и `BOT_MODE=polling`.

## 🗄 Supabase вместо JSON-файлов (необязательно)

На бесплатном тарифе Render файловая система эфемерная: чтобы сохранения
не пропадали после перезапуска, подключите бесплатный Postgres Supabase.

1. Создайте проект на [supabase.com](https://supabase.com), в SQL Editor выполните:

```sql
create table egor_saves (
    user_id text primary key,
    data jsonb not null,
    updated_at timestamptz not null default now()
);

alter table egor_saves enable row level security;

-- Доступ только service_role-ключом (Project Settings → API):
create policy "service full access" on egor_saves
    for all using (true) with check (true);
```

2. В переменные окружения приложения добавьте `SUPABASE_URL` и `SUPABASE_KEY`
   (service_role key). Хранилище переключится автоматически, миграция не нужна.

## 🕹 Подключение Telegram Mini App

Вариант 1 (просто): бот сам показывает inline-кнопку **«Открыть Mini App»**,
если задан `WEBAPP_URL`.

Вариант 2 (кнопка меню): в @BotFather → `/setmenubutton` → укажите адрес
`WEBAPP_URL`. Подпись `initData` проверяется на сервере (HMAC-SHA256),
подделать пользователя нельзя.

## 🧑‍💻 Как добавить контент

Весь контент — данные в `game/content.py`, код трогать не нужно.

Новая случайная сцена: добавьте словарь в `RANDOM_SCENES` (поле `"random": True`),
ссылайтесь на существующие предметы/навыки. Новый предмет — словарь в `ITEMS`.
Сюжетные дни привязаны в `DAY_SCENES`.

Пример варианта выбора:

```python
{
    "label": "Нарисовать печать красной ручкой",
    "hint": "Нужна красная ручка. Шанс низкий",
    "requires": {"item": "red_pen"},
    "chance": 0.35,                              # базовый шанс успеха
    "skill_bonus": {"seals": 0.12},             # +12% за уровень навыка
    "success": {"text": "...", "effects": {"authority": 10, "xp": {"seals": 3}}},
    "failure": {"text": "...", "effects": {"authority": -14}},
    "next": "__advance__",                      # закончить рабочий день
}
```

Ключи эффектов: `energy`, `mood`, `authority`, `money`, `xp`, `add_item`,
`remove_item`, `add_charge`, `use_charge`, `flags`, `absurd`.
Требования `requires`: `item`, `no_item`, `charge`, `money`, `authority`,
`skill`, `skill_total`, `flag`.

После правок запустите `pytest -q` — тест целостности контента проверит,
что все ссылки (предметы, навыки, сцены, концовки) существуют.
