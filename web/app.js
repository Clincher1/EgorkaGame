/* «ПТОшник против Системы» — фронтенд без сборки: ванильный JS + fetch.
 *
 * Платформа определяется автоматически по параметрам запуска:
 *   1. VK Mini App  — vk_app_id + sign в URL: VK Bridge, сохранения в VK Storage;
 *   2. Telegram     — tgWebAppData в URL: скрипт Telegram подгружается только тут;
 *   3. Обычный браузер (по умолчанию) — анонимный id в localStorage.
 */
"use strict";

// ---------------------------------------------------------------------------
// Определение платформы
// ---------------------------------------------------------------------------

const urlParams = new URLSearchParams(window.location.search);
const Platform = {
  isVK: urlParams.has("vk_app_id") && urlParams.has("sign"),
  isTG: urlParams.has("tgWebAppData"),
};

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.onload = resolve;
    script.onerror = () => reject(new Error("Не удалось загрузить " + src));
    document.head.appendChild(script);
  });
}

// ---------------------------------------------------------------------------
// VK Mini App: Bridge + VK Storage, состояние гоняем через сервер в каждом запросе
// ---------------------------------------------------------------------------

const VKMode = (() => {
  if (!Platform.isVK) return null;

  const bridge = window.vkBridge;
  const launch = Object.fromEntries(urlParams.entries());
  const STORAGE_KEY = "pto_save_v1";
  let save = "";

  const PATHS = {
    "/api/state": "/api/vk/state",
    "/api/choose": "/api/vk/choose",
    "/api/use": "/api/vk/use",
    "/api/reset": "/api/vk/reset",
    "/api/ad/reward": "/api/vk/ad",
  };

  async function init() {
    if (!bridge) throw new Error("VK Bridge не загрузился");
    await bridge.send("VKWebAppInit");
    const res = await bridge.send("VKWebAppStorageGet", { keys: [STORAGE_KEY] });
    const found = (res.keys || []).find((k) => k.key === STORAGE_KEY);
    save = found?.value || "";
  }

  async function persist(nextSave) {
    if (!nextSave || nextSave === save) return;
    save = nextSave;
    await bridge.send("VKWebAppStorageSet", { key: STORAGE_KEY, value: save });
  }

  async function call(path, payload) {
    const resp = await fetch(PATHS[path] || path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ launch, save, ...payload }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || data.reason || resp.statusText);
    await persist(data.save);
    return data;
  }

  async function showRewardedAd() {
    // Актуальный метод: нативная rewarded-реклама с водопадом заглушек.
    try {
      const res = await bridge.send("VKWebAppShowNativeAds", {
        ad_format: "reward",
        use_waterfall: true,
      });
      if (res.result === true) return true;
    } catch (_err) {
      // Старый метод оставлен как запасной для старых клиентов VK.
      try {
        const legacy = await bridge.send("VKWebAppShowRewardVideo");
        if (legacy.result === true) return true;
      } catch (_err2) {
        /* упадём в общую ветку «ролик недоступен» */
      }
    }
    return false;
  }

  return { init, call, showRewardedAd };
})();

// ---------------------------------------------------------------------------
// Telegram Mini App (скрипт подгружается лениво — в VK-сборке его нет вообще)
// ---------------------------------------------------------------------------

let tg = null;

async function initTelegram() {
  if (!Platform.isTG) return;
  if (!window.Telegram) {
    await loadScript("https://telegram.org/js/telegram-web-app.js");
  }
  tg = window.Telegram.WebApp;
  tg.ready();
  tg.expand();
}

// ---------------------------------------------------------------------------
// Веб-режим: анонимный идентификатор в localStorage
// ---------------------------------------------------------------------------

function getWebUserId() {
  let id = localStorage.getItem("egor_user_id");
  if (!id) {
    id = "web-" + crypto.randomUUID();
    localStorage.setItem("egor_user_id", id);
  }
  return id;
}

async function webCall(path, payload) {
  const body = tg && tg.initData ? { initData: tg.initData } : { user_id: getWebUserId() };
  Object.assign(body, payload);
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.error || err.reason || resp.statusText);
  }
  return resp.json();
}

// Единая точка обращения к API для всех платформ.
async function api(path, payload = {}) {
  if (Platform.isVK) return VKMode.call(path, payload);
  return webCall(path, payload);
}

// Сервер в VK-режиме всегда отвечает обёрткой {view, save, messages},
// а веб-эндпоинт state/reset возвращает «голый» view — приводим к одному виду.
function unwrap(data) {
  return data.view ? data : { view: data, messages: [] };
}

const el = (id) => document.getElementById(id);

function bar(label, value, cls, suffix = "") {
  const row = document.createElement("div");
  row.className = "stat-row";
  const lab = document.createElement("span");
  lab.className = "stat-label";
  lab.textContent = label;
  const track = document.createElement("div");
  track.className = "bar-track";
  const fill = document.createElement("div");
  fill.className = "bar-fill " + cls + (value <= 20 ? " low" : "");
  fill.style.width = Math.max(0, Math.min(100, value)) + "%";
  track.appendChild(fill);
  const val = document.createElement("span");
  val.className = "stat-value";
  val.textContent = value + suffix;
  row.append(lab, track, val);
  return row;
}

function renderStats(view) {
  const panel = el("stats-panel");
  panel.innerHTML = "";
  const s = view.stats;
  panel.append(
    bar("⚡ Энергия", s.energy, "bar-energy"),
    bar("🙂 Настроение", s.mood, "bar-mood"),
    bar("🎖 Авторитет", s.authority, "bar-authority"),
  );
  const money = document.createElement("div");
  money.className = "stat-row";
  money.innerHTML =
    '<span class="stat-label">💳 Деньги</span><span></span><span class="stat-value money"></span>';
  money.querySelector(".money").textContent = s.money + " ₽";
  panel.appendChild(money);
  el("day-badge").textContent = "день " + view.day;
}

function renderSkills(view) {
  const ul = el("skills");
  ul.innerHTML = "";
  for (const skill of view.skills) {
    const li = document.createElement("li");
    const stars = "★".repeat(skill.level) + "☆".repeat(5 - skill.level);
    li.innerHTML = `<span class="stars">${stars}</span> `;
    li.appendChild(document.createTextNode(skill.title));
    ul.appendChild(li);
  }
}

function renderInventory(view) {
  const ul = el("inventory");
  ul.innerHTML = "";
  if (view.inventory.length === 0) {
    const li = document.createElement("li");
    li.textContent = "пусто";
    li.style.color = "var(--muted)";
    ul.appendChild(li);
    return;
  }
  for (const item of view.inventory) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.textContent =
      item.emoji + " " + item.name + (item.charges != null ? ` (${item.charges})` : "");
    li.appendChild(name);
    if (item.consumable && (item.charges == null || item.charges > 0)) {
      const btn = document.createElement("button");
      btn.className = "inv-use";
      btn.textContent = "Использовать";
      btn.dataset.action = "use";
      btn.dataset.item = item.id;
      li.appendChild(btn);
    }
    ul.appendChild(li);
  }
}

function isBadMessage(text) {
  return text.startsWith("❌") || text.startsWith("⛔") || text.includes("Провал");
}

function renderMessages(messages) {
  const box = el("messages");
  box.innerHTML = "";
  if (!messages || messages.length === 0) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  for (const text of messages) {
    const div = document.createElement("div");
    div.className = isBadMessage(text) ? "msg-bad" : "msg-ok";
    div.textContent = text;
    box.appendChild(div);
  }
}

function renderArt(view) {
  const bg = el("scene-bg");
  if (view.art?.background) {
    bg.src = view.art.background;
    bg.parentElement.hidden = false;
  } else {
    bg.parentElement.hidden = true;
  }
  const portrait = el("scene-portrait");
  if (view.art?.portrait) {
    portrait.src = view.art.portrait;
    portrait.hidden = false;
  } else {
    portrait.hidden = true;
    portrait.removeAttribute("src");
  }
}

function renderScene(view, messages) {
  renderArt(view);
  el("scene-emoji").textContent = view.scene.emoji;
  el("scene-title").textContent = view.scene.title;
  el("scene-text").textContent = view.scene.text;
  renderMessages(messages);

  const options = el("options");
  options.innerHTML = "";
  for (const opt of view.options) {
    const btn = document.createElement("button");
    btn.className = "option-btn";
    btn.dataset.action = "choose";
    btn.dataset.index = opt.index;
    const label = document.createElement("span");
    label.textContent = (opt.available ? "" : "🔒 ") + opt.label;
    btn.appendChild(label);
    if (opt.hint) {
      const hint = document.createElement("span");
      hint.className = "hint";
      hint.textContent = opt.hint;
      btn.appendChild(hint);
    }
    if (!opt.available) {
      btn.disabled = true;
      btn.title = opt.reason || "Недоступно";
      if (opt.reason) {
        const why = document.createElement("span");
        why.className = "hint";
        why.textContent = "🚫 " + opt.reason;
        btn.appendChild(why);
      }
    }
    options.appendChild(btn);
  }

  renderAdBanner(view);

  const overlay = el("ending-overlay");
  if (view.over) {
    el("ending-emoji").textContent = view.scene.emoji;
    el("ending-title").textContent = view.scene.title;
    el("ending-text").textContent = view.scene.text;
    overlay.hidden = false;
  } else {
    overlay.hidden = true;
  }
}

function render(view, messages = null) {
  renderStats(view);
  renderSkills(view);
  renderInventory(view);
  renderScene(view, messages);
}

async function refresh() {
  const { view } = unwrap(await api("/api/state"));
  render(view);
}

async function choose(index) {
  const data = await api("/api/choose", { option_index: index });
  SoundFX.play(soundForMessages(data.messages, data.view));
  render(data.view, data.messages);
}

async function useItem(itemId) {
  const data = await api("/api/use", { item_id: itemId });
  SoundFX.play(soundForMessages(data.messages, data.view));
  render(data.view, data.messages);
}

async function watchAd() {
  // В VK сначала показываем настоящий rewarded-ролик через Bridge:
  // награду начисляет сервер только после успешного показа, кулдаун — там же.
  if (Platform.isVK) {
    const watched = await VKMode.showRewardedAd();
    if (!watched) {
      alert("Ролик сейчас недоступен. Силы восстановятся сами по таймеру.");
      return;
    }
  }
  const data = unwrap(await api("/api/ad/reward", {}));
  SoundFX.play("reward");
  render(data.view, data.messages);
}

async function reset() {
  const { view } = unwrap(await api("/api/reset"));
  render(view);
}

function renderAdBanner(view) {
  let banner = el("ad-banner");
  if (!view.over && view.exhausted) {
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "ad-banner";
      banner.className = "ad-banner";
      banner.innerHTML =
        '<button class="btn-ad" data-action="ad">📺 Посмотреть ролик — вернуться сразу</button>';
      el("options").before(banner);
    }
    banner.hidden = false;
  } else if (banner) {
    banner.hidden = true;
  }
}

document.addEventListener("click", async (event) => {
  const btn = event.target.closest("button[data-action]");
  if (!btn || btn.disabled) return;
  try {
    btn.disabled = true;
    if (btn.dataset.action === "choose") {
      await choose(Number(btn.dataset.index));
    } else if (btn.dataset.action === "use") {
      await useItem(btn.dataset.item);
    } else if (btn.dataset.action === "ad") {
      await watchAd();
    }
  } catch (err) {
    alert("Ошибка: " + err.message);
    await refresh();
  } finally {
    btn.disabled = false;
  }
});

el("reset-btn").addEventListener("click", async () => {
  if (confirm("Начать игру заново? Текущий прогресс будет стёрт.")) {
    try {
      await reset();
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }
});
el("ending-restart").addEventListener("click", reset);

el("mute-btn").addEventListener("click", () => {
  const muted = SoundFX.toggle();
  el("mute-btn").textContent = muted ? "🔇" : "🔊";
});
if (SoundFX.isMuted()) el("mute-btn").textContent = "🔇";

// ---------------------------------------------------------------------------
// Меню и модалки
// ---------------------------------------------------------------------------

function showMenu() {
  el("main-menu").hidden = false;
}
function hideMenu() {
  el("main-menu").hidden = true;
}
function openModal(id) {
  el(id).hidden = false;
}
function closeModals() {
  document.querySelectorAll(".modal-overlay").forEach((m) => (m.hidden = true));
}

el("menu-btn").addEventListener("click", showMenu);
el("btn-continue").addEventListener("click", () => {
  SoundFX.play("click");
  hideMenu();
});
el("btn-new").addEventListener("click", async () => {
  SoundFX.play("click");
  await reset();
  hideMenu();
});
el("btn-rules").addEventListener("click", () => {
  SoundFX.play("click");
  openModal("rules-modal");
});
el("btn-policy").addEventListener("click", () => {
  SoundFX.play("click");
  openModal("privacy-modal");
});
el("footer-policy").addEventListener("click", (e) => {
  e.preventDefault();
  openModal("privacy-modal");
});
document.querySelectorAll(".modal-close").forEach((btn) =>
  btn.addEventListener("click", () => {
    SoundFX.play("click");
    closeModals();
  })
);
document.querySelectorAll(".modal-overlay").forEach((overlay) =>
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModals();
  })
);

// ---------------------------------------------------------------------------
// Старт: инициализация платформы -> первая загрузка -> главное меню
// ---------------------------------------------------------------------------

async function bootstrap() {
  try {
    if (Platform.isVK) {
      await VKMode.init();
    } else if (Platform.isTG) {
      await initTelegram();
    }
    await refresh();
    showMenu();
  } catch (err) {
    el("scene-title").textContent = "Не удалось загрузить игру";
    el("scene-text").textContent = String(err.message || err);
  }
}

bootstrap();
