/* Ретро-звуки интерфейса. Файлы синтезируются tools/make_sounds.py. */
"use strict";

const SoundFX = (() => {
  const files = {
    click: "/sounds/click.wav",
    success: "/sounds/success.wav",
    fail: "/sounds/fail.wav",
    reward: "/sounds/reward.wav",
    exhaust: "/sounds/exhaust.wav",
  };
  const cache = {};
  let muted = localStorage.getItem("egor_muted") === "1";

  function audio(name) {
    if (!cache[name]) {
      cache[name] = new Audio(files[name]);
      cache[name].preload = "auto";
    }
    return cache[name];
  }

  function play(name) {
    if (muted || !files[name]) return;
    const clip = audio(name);
    clip.currentTime = 0;
    // Браузеры разрешают звук только после действия пользователя —
    // все вызовы у нас происходят по клику, так что promise всегда валиден.
    clip.play().catch(() => {});
  }

  function toggle() {
    muted = !muted;
    localStorage.setItem("egor_muted", muted ? "1" : "0");
    return muted;
  }

  function isMuted() {
    return muted;
  }

  return { play, toggle, isMuted };
})();

/* Выбор звука по содержимому ответа сервера */
function soundForMessages(messages, view) {
  if (view && view.exhausted) return "exhaust";
  const text = (messages || []).join(" ");
  if (text.includes("❌") || text.includes("Провал") || text.includes("⛔")) {
    return "fail";
  }
  if (text.includes("повышен") || text.includes("Успех") || text.includes("КОНЦОВКА")) {
    return "success";
  }
  return "click";
}
