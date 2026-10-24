/* «ПТОшник Егор» — фронтенд без сборки: ванильный JS + fetch. */
"use strict";

const tg = window.Telegram?.WebApp ?? null;
if (tg) {
  tg.ready();
  tg.expand();
}

function getUserId() {
  let id = localStorage.getItem("egor_user_id");
  if (!id) {
    id = "web-" + crypto.randomUUID();
    localStorage.setItem("egor_user_id", id);
  }
  return id;
}

async function api(path, payload = {}) {
  const body = tg && tg.initData ? { initData: tg.initData } : { user_id: getUserId() };
  Object.assign(body, payload);
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.reason || resp.statusText);
  }
  return resp.json();
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

function renderScene(view, messages) {
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
  const view = await api("/api/state");
  render(view);
}

async function choose(index) {
  const data = await api("/api/choose", { option_index: index });
  render(data.view, data.messages);
}

async function useItem(itemId) {
  const data = await api("/api/use", { item_id: itemId });
  render(data.view, data.messages);
}

async function reset() {
  const view = await api("/api/reset");
  render(view);
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
    }
  } catch (err) {
    alert("Ошибка: " + err.message);
    await refresh();
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

refresh().catch((err) => {
  el("scene-title").textContent = "Не удалось загрузить игру";
  el("scene-text").textContent = String(err);
});
