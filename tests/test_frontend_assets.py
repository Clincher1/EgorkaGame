"""Стражи фронтенда: модерационные инварианты VK и наличие всех ассетов."""

import re
from pathlib import Path

from game import content

WEB = Path(__file__).parent.parent / "web"
INDEX_HTML = (WEB / "index.html").read_text(encoding="utf-8")
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")
SOUND_JS = (WEB / "sound.js").read_text(encoding="utf-8")


def test_index_loads_vk_bridge_and_not_telegram_script():
    # VK Bridge подключён официальным CDN-пакетом.
    assert "@vkontakte/vk-bridge" in INDEX_HTML
    # Никаких скриптов чужих платформ в странице, которая отдаётся игрокам.
    assert "telegram.org" not in INDEX_HTML
    assert "telegram-web-app" not in INDEX_HTML


def test_app_js_implements_vk_storage_and_rewarded_ads():
    assert "vk_app_id" in APP_JS  # автоопределение VK-запуска
    assert "VKWebAppInit" in APP_JS
    assert "VKWebAppStorageGet" in APP_JS
    assert "VKWebAppStorageSet" in APP_JS
    assert "VKWebAppShowNativeAds" in APP_JS  # актуальная rewarded-реклама
    assert "/api/vk/state" in APP_JS


def test_no_telegram_in_player_facing_frontend():
    # Продукт — VK-only: ни SDK, ни упоминаний чужих платформ в выдаваемых
    # браузеру файлах быть не должно (требование модерации 3.13/4.1.8).
    for path in WEB.rglob("*"):
        if path.suffix not in (".js", ".html", ".css"):
            continue
        text = path.read_text(encoding="utf-8").lower()
        assert "telegram" not in text, path
        assert "tgwebapp" not in text, path


def test_default_mode_remains_anonymous_web():
    # Без платформенных параметров запуска — старое поведение: localStorage-id.
    assert 'localStorage.getItem("egor_user_id")' in APP_JS


def test_every_art_asset_exists_on_disk():
    referenced = set(content.SCENE_BACKGROUNDS.values())
    referenced.add(content.DEFAULT_BACKGROUND)
    referenced.update(content.SCENE_PORTRAITS.values())
    img_dir = WEB / "static" / "img"
    for filename in referenced:
        assert (img_dir / filename).is_file(), filename


def test_every_sound_asset_exists_on_disk():
    for wav in re.findall(r"/sounds/([\w-]+\.wav)", SOUND_JS):
        assert (WEB / "static" / "sounds" / wav).is_file(), wav


def test_branding_matches_registered_vk_name():
    assert "ПТОшник против Системы" in INDEX_HTML
    # Старое рабочее название не должно оставаться в витринных текстах.
    assert "Битва за Участок" not in INDEX_HTML
