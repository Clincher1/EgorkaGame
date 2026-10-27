"""Оптимизация арта для веба: фоны 1280px JPEG, портреты/иконка 512px JPEG.

Запуск: python tools/optimize_images.py
Берёт PNG из web/static/img, кладёт сжатые JPG рядом и удаляет исходники,
чтобы в репозиторий не попали многомегабайтные файлы.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

IMG_DIR = Path(__file__).parent.parent / "web" / "static" / "img"

PORTRAITS = {"egor", "petrovich", "ivanych", "svetlana", "icon"}
BACKGROUND_MAX_WIDTH = 1280
PORTRAIT_SIZE = 512
JPEG_QUALITY = 82


def main() -> None:
    total_before = total_after = 0
    for png in sorted(IMG_DIR.glob("*.png")):
        name = png.stem
        total_before += png.stat().st_size
        img = Image.open(png).convert("RGB")

        if name in PORTRAITS:
            img.thumbnail((PORTRAIT_SIZE, PORTRAIT_SIZE), Image.LANCZOS)
        else:
            img.thumbnail((BACKGROUND_MAX_WIDTH, 9999), Image.LANCZOS)

        out = png.with_suffix(".jpg")
        img.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
        total_after += out.stat().st_size
        png.unlink()
        print(f"{name}: {img.size[0]}x{img.size[1]}, {out.stat().st_size // 1024} КБ")

    print(
        f"Итого: {total_before // 1024} КБ -> {total_after // 1024} КБ "
        f"(-{100 - total_after * 100 // total_before}%)"
    )


if __name__ == "__main__":
    main()
