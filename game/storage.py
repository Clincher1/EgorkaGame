"""Хранилище сохранений.

Две реализации за одним интерфейсом:
  * JsonStorage  — файлы в локальной папке (по умолчанию, работает везде);
  * SupabaseStorage — бесплатный Postgres в Supabase (REST/PostgREST).

Выбор хранилища — через переменные окружения (см. .env.example).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Protocol

import aiohttp

from .models import GameState

_SAFE_ID = re.compile(r"[^A-Za-z0-9_@.-]+")


def safe_filename(user_id: str) -> str:
    """Превращает любой user_id в безопасное имя файла."""
    return _SAFE_ID.sub("_", str(user_id))[:120]


class Storage(Protocol):
    async def load(self, user_id: str | int) -> GameState | None: ...

    async def save(self, state: GameState) -> None: ...

    async def delete(self, user_id: str | int) -> None: ...


# ---------------------------------------------------------------------------
# JSON-файлы
# ---------------------------------------------------------------------------

class JsonStorage:
    """Хранит каждое сохранение в отдельном JSON-файле."""

    def __init__(self, directory: str = "saves") -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, user_id: str | int) -> Path:
        return self.dir / f"{safe_filename(str(user_id))}.json"

    async def load(self, user_id: str | int) -> GameState | None:
        path = self._path(user_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return GameState.from_dict(data)
        except (json.JSONDecodeError, TypeError, ValueError):
            # Битый файл не должен ронять бота — начнём новую игру
            return None

    async def save(self, state: GameState) -> None:
        path = self._path(state.user_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)  # атомарная запись

    async def delete(self, user_id: str | int) -> None:
        path = self._path(user_id)
        if path.exists():
            path.unlink()


# ---------------------------------------------------------------------------
# Supabase (PostgREST)
# ---------------------------------------------------------------------------

class SupabaseStorage:
    """Сохранения в таблице Supabase через REST, без тяжёлых SDK.

    SQL для создания таблицы (см. README):
        create table egor_saves (
            user_id text primary key,
            data jsonb not null,
            updated_at timestamptz not null default now()
        );
        alter table egor_saves enable row level security;
        create policy "service full access" on egor_saves
            for all using (true) with check (true);  -- доступ только service_role-ключом
    """

    TABLE = "egor_saves"

    def __init__(self, url: str, key: str) -> None:
        self.base = url.rstrip("/")
        self.key = key
        self._session: aiohttp.ClientSession | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

    async def _client(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def load(self, user_id: str | int) -> GameState | None:
        session = await self._client()
        url = f"{self.base}/rest/v1/{self.TABLE}?user_id=eq.{user_id}&select=data"
        async with session.get(url, headers=self._headers()) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"Supabase load error {resp.status}: {await resp.text()}")
            rows = await resp.json()
        if not rows:
            return None
        return GameState.from_dict(rows[0]["data"])

    async def save(self, state: GameState) -> None:
        session = await self._client()
        url = f"{self.base}/rest/v1/{self.TABLE}"
        headers = {**self._headers(), "Prefer": "resolution=merge-duplicates"}
        payload = {"user_id": state.user_id, "data": state.to_dict()}
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"Supabase save error {resp.status}: {await resp.text()}")

    async def delete(self, user_id: str | int) -> None:
        session = await self._client()
        url = f"{self.base}/rest/v1/{self.TABLE}?user_id=eq.{user_id}"
        async with session.delete(url, headers=self._headers()) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"Supabase delete error {resp.status}: {await resp.text()}")


# ---------------------------------------------------------------------------
# Фабрика
# ---------------------------------------------------------------------------

def build_storage() -> Storage:
    """Создаёт хранилище по переменным окружения."""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if supabase_url and supabase_key:
        return SupabaseStorage(supabase_url, supabase_key)  # type: ignore[return-value]
    return JsonStorage(os.getenv("SAVES_DIR", "saves"))
