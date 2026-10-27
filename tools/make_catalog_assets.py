"""Генерация изображений для карточки VK Mini Apps в каталоге.

Запуск: .venv/bin/python tools/make_catalog_assets.py

Результат (web/static/img/):
  icon.png            — иконка 512×512 PNG (конверсия существующей icon.jpg);
  cover-1080x608.png  — обложка каталога 1080×608 (16:9) на основе menu-bg.jpg
                        с заголовком игры и слоганом в ретро-палитре.

Скриншоты игровых экранов генератор не делает: правила VK требуют реальные
экраны приложения, их снимают вручную (десктоп-браузер или телефон в VK).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "web" / "static" / "img"

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

GOLD = (216, 166, 87)
CREAM = (240, 230, 210)
DARK = (8, 20, 16)


def make_icon_png() -> Path:
    src = Image.open(IMG / "icon.jpg").convert("RGB")
    if src.size != (512, 512):
        src = src.resize((512, 512), Image.LANCZOS)
    out = IMG / "icon.png"
    src.save(out, "PNG", optimize=True)
    return out


def cover_crop(base: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Масштаб с заполнением и центральным кропом под 1080×608."""
    target_w, target_h = size
    scale = max(target_w / base.width, target_h / base.height)
    resized = base.resize(
        (round(base.width * scale), round(base.height * scale)), Image.LANCZOS
    )
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def make_cover() -> Path:
    w, h = 1080, 608
    canvas = cover_crop(Image.open(IMG / "menu-bg.jpg").convert("RGB"), (w, h))

    # Затемнение нижней трети — заголовок должен читаться на любом фоне.
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in range(h):
        if y < h // 2:
            alpha = 0
        else:
            alpha = int(210 * ((y - h / 2) / (h / 2)) ** 1.4)
        od.line([(0, y), (w, y)], fill=(*DARK, alpha))
    # Лёгкая вуаль по всему кадру для единства палитры.
    od.rectangle([0, 0, w, h], fill=(*DARK, 55))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(canvas)

    # Тонкая золотая рамка — единый стиль с игровой иконкой.
    frame = (*GOLD, 235)
    draw.rectangle([10, 10, w - 11, h - 11], outline=frame, width=4)
    draw.rectangle([18, 18, w - 19, h - 19], outline=(*GOLD, 110), width=1)

    title_font = ImageFont.truetype(FONT_BOLD, 54)
    slogan_font = ImageFont.truetype(FONT_MONO, 28)

    title = "ПТОшник против Системы"
    slogan = "— Бумажный Ад —"

    def centered(text: str, font, y: int, fill, shadow: bool = True) -> None:
        box = draw.textbbox((0, 0), text, font=font)
        tw = box[2] - box[0]
        x = (w - tw) // 2
        if shadow:
            draw.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0, 210))
        draw.text((x, y), text, font=font, fill=fill)

    centered(title, title_font, h - 158, (*GOLD, 255))
    centered(slogan, slogan_font, h - 84, (*CREAM, 235))

    out = IMG / "cover-1080x608.png"
    canvas.convert("RGB").save(out, "PNG", optimize=True)
    return out


def main() -> None:
    icon = make_icon_png()
    cover = make_cover()
    for p in (icon, cover):
        im = Image.open(p)
        print(f"{p.relative_to(ROOT)}: {im.size[0]}x{im.size[1]} {p.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
