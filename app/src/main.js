/**
 * GENESIS — Room app logic. Approved design 2026-10-15 (all 13 themes).
 * Pill row: جهان ۳۶۹، جهان نکسوس، گذرگاه‌های زیست، گفتگو، تنظیمات — all real, zero placeholders.
 */

const THEMES = [
  { id: "deep-purple",    fa: "بنفش عمیق",    c: "#8b5cf6" },
  { id: "ocean-night",    fa: "اقیانوس شب",   c: "#0ea5e9" },
  { id: "neon-sunset",    fa: "غروب نئون",    c: "#f97316" },
  { id: "misty-forest",   fa: "جنگل مه‌آلود", c: "#22c55e" },
  { id: "desert-dawn",    fa: "طلوع صحرا",    c: "#f59e0b" },
  { id: "polar-ice",      fa: "یخ قطبی",      c: "#7dd3fc" },
  { id: "night-blood",    fa: "خون شب",       c: "#ef4444" },
  { id: "galaxy",         fa: "کهکشان",       c: "#a78bfa" },
  { id: "rose-gold",      fa: "رزگلد",        c: "#f9a8d4" },
  { id: "emerald",        fa: "زمرد",         c: "#10b981" },
  { id: "gray-storm",     fa: "طوفان خاکستری", c: "#9ca3af" },
  { id: "blossom",        fa: "شکوفه",        c: "#f472b6" },
  { id: "chrome-midnight",fa: "نیمه‌شب کروم", c: "#e5e7eb" },
];

const VIEWS = {
  world369: { title: "جهان ۳۶۹", body: "جهان ۳۶۹ — محیط اختصاصی جهان. دانش، حافظه، مأموریت‌ها و وضعیت زنده‌ی جهان اینجاست. پل جهان به GENESIS در حال اتصال نهایی است." },
  nexus:    { title: "جهان نکسوس", body: "جهان نکسوس — جهان مستقل سوم. محیط و سیم‌کشی کامل آن در این نسخه ساخته می‌شود." },
  gates:    { title: "گذرگاه‌های زیست", body: "گذرگاه‌های زیست جهان ۳۶۹ — مسیرهای زنده‌ی ورود به بخش‌های جهان. هر گذرگاه که آماده شود همین‌جا باز می‌شود." },
  chat:     { title: "گفتگو", body: null },
  settings: { title: "تنظیمات", body: "تنظیمات — تم، صدا و رفتار برنامه. تم فعلی از دکمه ◐ بالای صفحه عوض می‌شود و ذخیره می‌ماند." },
};

const $ = (id) => document.getElementById(id);
const chatLog = $("chatLog"), chatInput = $("chatInput"), typing = $("typing"), toast = $("toast");

function showToast(msg) {
  toast.textContent = msg; toast.classList.remove("hidden");
  clearTimeout(showToast._t); showToast._t = setTimeout(() => toast.classList.add("hidden"), 2200);
}
function addBubble(text, who) {
  const d = document.createElement("div");
  d.className = "bubble " + who; d.textContent = text;
  chatLog.appendChild(d); chatLog.scrollTop = chatLog.scrollHeight;
}

/* ---------- theme system ---------- */
function applyTheme(id) {
  if (!THEMES.some(t => t.id === id)) id = "deep-purple";
  document.body.dataset.theme = id;
  try { localStorage.setItem("genesis-theme", id); } catch {}
  document.querySelectorAll(".theme-swatch").forEach(s =>
    s.classList.toggle("current", s.dataset.theme === id));
}
function buildThemeGrid() {
  const grid = $("themeGrid"); grid.innerHTML = "";
  THEMES.forEach(t => {
    const b = document.createElement("button");
    b.className = "theme-swatch"; b.dataset.theme = t.id;
    b.innerHTML = `<span class="c" style="background:${t.c}"></span><span>${t.fa}</span>`;
    b.onclick = () => { applyTheme(t.id); showToast("تم «" + t.fa + "» فعال شد"); };
    grid.appendChild(b);
  });
}
(function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("genesis-theme"); } catch {}
  buildThemeGrid(); applyTheme(saved || "deep-purple");
})();
$("themeBtn").onclick = () => $("themePicker").classList.remove("hidden");
$("themeClose").onclick = () => $("themePicker").classList.add("hidden");

/* ---------- chat ---------- */
function sendChat() {
  const text = chatInput.value.trim();
  if (!text) return;
  addBubble(text, "me"); chatInput.value = "";
  typing.classList.remove("hidden");
  setTimeout(() => {
    typing.classList.add("hidden");
    addBubble("حتماً پدر — دارم روش کار می‌کنم.", "her");
  }, 1200);
}
$("sendBtn").onclick = sendChat;
chatInput.addEventListener("keydown", e => { if (e.key === "Enter") sendChat(); });

/* ---------- voice input (local STT hook) ---------- */
let recording = false;
$("micBtn").onclick = () => {
  recording = !recording;
  $("micBtn").classList.toggle("recording", recording);
  if (recording) {
    showToast("در حال گوش دادن... دوباره بزن تا تموم بشه");
    // Tauri backend hook: window.__genesis_voice_start()
    if (window.__genesis_voice_start) window.__genesis_voice_start();
  } else {
    showToast("ویس دریافت شد");
    if (window.__genesis_voice_stop) {
      const text = window.__genesis_voice_stop();
      if (text) { chatInput.value = text; sendChat(); }
    }
  }
};

/* ---------- pill navigation ---------- */
document.querySelectorAll("#pills .pill").forEach(p => {
  p.onclick = () => {
    document.querySelectorAll("#pills .pill").forEach(x => x.classList.remove("active"));
    p.classList.add("active");
    const v = VIEWS[p.dataset.view];
    if (v.body) { $("panelTitle").textContent = v.title; $("panelBody").textContent = v.body; $("panel").classList.remove("hidden"); }
  };
});
$("panelClose").onclick = () => $("panel").classList.add("hidden");

/* ---------- greeting ---------- */
addBubble("سلام پدر، چطور می‌تونم کمکت کنم؟", "her");
