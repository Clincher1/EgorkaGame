"""Генератор ретро-звуков интерфейса (WAV, без сторонних библиотек).

Запуск:  python tools/make_sounds.py
Результат: web/static/sounds/*.wav — короткие синтезированные эффекты
в духе 8-битных RPG: клик, успех, провал, награда, истощение.
Лицензионных рисков нет, звук целиком синтезируется формулами.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 22050
OUT_DIR = Path(__file__).parent.parent / "web" / "static" / "sounds"


def _tone(freq: float, duration: float, volume: float = 0.35, shape: str = "square"):
    """Возвращает семплы одной ноты с мягким затуханием."""
    count = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(count):
        t = i / SAMPLE_RATE
        phase = 2 * math.pi * freq * t
        if shape == "square":
            value = 1.0 if math.sin(phase) >= 0 else -1.0
        elif shape == "triangle":
            value = 2 / math.pi * math.asin(math.sin(phase))
        else:  # sine
            value = math.sin(phase)
        # Огибатель: быстрая атака, плавное затухание, без щелчков
        attack = min(1.0, i / max(1, SAMPLE_RATE * 0.005))
        decay = 1.0 - (i / max(1, count)) ** 2
        samples.append(value * volume * attack * decay)
    return samples


def _sequence(notes: list[tuple[float, float, str]], gap: float = 0.02):
    """Склеивает ноты с короткой паузой."""
    silence = [0.0] * int(SAMPLE_RATE * gap)
    out: list[float] = []
    for freq, duration, shape in notes:
        if out:
            out.extend(silence)
        out.extend(_tone(freq, duration, shape=shape))
    return out


def _save(name: str, samples: list[float]) -> None:
    path = OUT_DIR / name
    with wave.open(str(path), "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # 16 бит
        wav.setframerate(SAMPLE_RATE)
        frames = b"".join(
            struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples
        )
        wav.writeframes(frames)
    print(f"{name}: {len(samples) / SAMPLE_RATE:.2f} c, {path.stat().st_size} Б")


SOUNDS = {
    # Короткий клик кнопки
    "click.wav": [(660, 0.06, "square")],
    # Восходящее арпеджио — успешное действие
    "success.wav": [
        (523.25, 0.10, "square"),   # C5
        (659.25, 0.10, "square"),   # E5
        (783.99, 0.10, "square"),   # G5
        (1046.5, 0.18, "square"),   # C6
    ],
    # Нисходящий «буззер» — провал
    "fail.wav": [
        (311.13, 0.14, "saw" if False else "triangle"),  # Eb4
        (233.08, 0.22, "triangle"),                      # Bb3
    ],
    # Монетка-награда за рекламу
    "reward.wav": [
        (987.77, 0.08, "square"),   # B5
        (1318.5, 0.22, "square"),   # E6
    ],
    # Усталость: низкий печальный спуск
    "exhaust.wav": [
        (220.0, 0.20, "sine"),
        (164.81, 0.35, "sine"),
    ],
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, notes in SOUNDS.items():
        _save(name, _sequence(notes))
    print(f"Готово: {len(SOUNDS)} файлов в {OUT_DIR}")


if __name__ == "__main__":
    main()
