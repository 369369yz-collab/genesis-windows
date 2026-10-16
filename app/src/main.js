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
  world369: { title: "جهان ۳۶۹", live: "world369" },
  nexus:    { title: "جهان نکسوس", live: "nexus" },
  gates:    { title: "گذرگاه‌های زیست", live: "gates" },
  chat:     { title: "گفتگو", body: null },
  settings: { title: "تنظیمات", body: "تنظیمات — تم، صدا و رفتار برنامه. تم فعلی از دکمه ◐ بالای صفحه عوض می‌شود و ذخیره می‌ماند." },
};

/* ---------- live world panels: zero placeholders ----------
   جهان ۳۶۹ / نکسوس / گذرگاه‌ها از سرویس مغز (world_state) می‌خونن —
   دانشِ واقعی جهان + آمارِ زنده‌ی لحظه‌ای (حافظه، آپتایم، نگهبان‌های کدکس). */
async function renderLivePanel(kind) {
  const titles = { world369: "جهان ۳۶۹", nexus: "جهان نکسوس", gates: "گذرگاه‌های زیست" };
  $("panelTitle").textContent = titles[kind];
  $("panelBody").innerHTML = "<div>در حال خواندن از مغز...</div>";
  $("panel").classList.remove("hidden");
  if (!invoke) { $("panelBody").textContent = "مغز در این محیط در دسترس نیست"; return; }
  try {
    const raw = await invoke("world_state");
    const st = JSON.parse(raw);
    if (!st.ok) throw new Error("bad state");
    const live = st.live || {};
    const upMin = Math.round((live.uptime_s || 0) / 60);
    if (kind === "world369") {
      const w = (st.worlds || {})["369"] || {};
      $("panelBody").innerHTML =
        `<div class="set-row"><b>${w.name || "جهان ۳۶۹"}</b></div>` +
        `<div style="margin:6px 0;font-size:13px">${w.description || ""}</div>` +
        `<div class="set-row"><b>حافظه‌ی زنده</b><span>${live.facts || 0} دانستنی، ${live.exchanges || 0} گفتگو</span></div>` +
        `<div class="set-row"><b>نگهبان‌های کدکس</b><span>${live.codex_guards || 0} قانونِ اجرایی</span></div>` +
        `<div class="set-row"><b>مغز</b><span>روشن از ${upMin} دقیقه پیش — مدل ${live.llama_alive ? "آماده" : "در حال آماده‌سازی"}</span></div>`;
    } else if (kind === "nexus") {
      const n = (st.worlds || {}).nexus || {}, g = (st.worlds || {}).genesis || {};
      $("panelBody").innerHTML =
        `<div class="set-row"><b>${n.name || "جهان نکسوس"}</b></div>` +
        `<div style="margin:6px 0;font-size:13px">${n.description || ""}</div>` +
        `<div class="set-row"><b>${g.name || "جهان جنسیس"}</b></div>` +
        `<div style="margin:6px 0;font-size:13px">${g.description || ""}</div>`;
    } else {
      const gates = st.gates || [];
      $("panelBody").innerHTML = gates.map(gt =>
        `<div class="set-row"><b>${gt.name}</b><span>${gt.description}</span></div>`).join("") ||
        "<div>گذرگاهی ثبت نشده</div>";
    }
  } catch (e) {
    $("panelBody").textContent = "خواندن وضعیت جهان ممکن نشد — یه بار دیگه امتحان کن، پدر.";
  }
}

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

/* ---------- chat: REAL local-model inference (no canned replies) ---------- */
function addErrorBubble(text) {
  const d = document.createElement("div");
  d.className = "bubble her error"; d.textContent = "⚠ " + text;
  chatLog.appendChild(d); chatLog.scrollTop = chatLog.scrollHeight;
}
async function sendChat() {
  const text = chatInput.value.trim();
  if (!text) return;
  addBubble(text, "me"); chatInput.value = "";
  typing.classList.remove("hidden");
  try {
    if (!invoke) throw new Error("no-invoke");
    const reply = await invoke("chat_send", { prompt: text });
    typing.classList.add("hidden");
    addBubble(reply, "her");
  } catch (e) {
    typing.classList.add("hidden");
    const msg = (e && e.toString && e.toString()) || "";
    addErrorBubble(msg || "مغزم جواب نداد — یه بار دیگه امتحان کن، پدر.");
  }
}
$("sendBtn").onclick = sendChat;
chatInput.addEventListener("keydown", e => { if (e.key === "Enter") sendChat(); });

/* ---------- voice input: local whisper STT, zero cloud ---------- */
/* IPC init — UNCONDITIONAL. Never gate on window.__TAURI__ again: Tauri v2
   defaults withGlobalTauri=false, so the global is undefined in the packaged
   webview and the gate left invoke null forever (RED 2026-10-16, run 38805846150).
   The import itself fails only in a plain-browser dev env, which the catch covers. */
var invoke = null;
try {
  const core = await import("@tauri-apps/api/core");
  invoke = core.invoke;
} catch (e) { /* plain-browser test env: no Tauri */ }

/* ---------- NEVER-AGAIN gate: Tauri IPC liveness (RED 2026-10-16) ----------
   The runtime ALWAYS injects window.__TAURI_INTERNALS__ into a real Tauri webview
   (dev and packaged alike), independent of withGlobalTauri. If we're inside one
   but invoke is dead, chat is silently dead — prove liveness instead of hoping. */
(function ipcLivenessGate() {
  if (!window.__TAURI_INTERNALS__) return; /* plain-browser dev: nothing to gate */
  function loud(msg) {
    try { console.error(msg); } catch (e) {}
    try { addErrorBubble("⚠ " + msg); } catch (e2) {}
  }
  if (!invoke) {
    loud("TAURI-IPC-LIVENESS: FAIL — Tauri webview detected but invoke is null; chat cannot reach the brain. Report this bug.");
    return;
  }
  invoke("ipc_ping").then(function () {
    try { console.log("TAURI-IPC-LIVENESS: OK"); } catch (e) {}
  }).catch(function (e) {
    loud("TAURI-IPC-LIVENESS: FAIL — ipc_ping threw: " + (e && e.toString ? e.toString() : e));
  });
})();

let audioCtx = null, audioStream = null, audioProc = null, audioChunks = [];

function encodeWav16(samples, sampleRate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const wstr = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  wstr(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); wstr(8, "WAVE");
  wstr(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, sampleRate, true); v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true); wstr(36, "data");
  v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Uint8Array(buf);
}

async function voiceEngineReady() {
  if (!invoke) return { installed: false, testEnv: true };
  try { return await invoke("voice_status"); }
  catch (e) { return { installed: false, error: String(e) }; }
}

let recording = false;
$("micBtn").onclick = async () => {
  if (!recording) {
    const st = await voiceEngineReady();
    if (!st.installed && !st.testEnv) {
      showToast("موتور ویس هنوز نصب نیست — متن بنویس پدر");
      return;
    }
    try {
      audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      showToast("دسترسی به میکروفون داده نشد");
      return;
    }
    audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    const src = audioCtx.createMediaStreamSource(audioStream);
    audioProc = audioCtx.createScriptProcessor(4096, 1, 1);
    audioChunks = [];
    audioProc.onaudioprocess = (e) => audioChunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    src.connect(audioProc); audioProc.connect(audioCtx.destination);
    recording = true;
    $("micBtn").classList.add("recording");
    showToast("در حال گوش دادن... دوباره بزن تا تموم بشه");
  } else {
    recording = false;
    $("micBtn").classList.remove("recording");
    const flat = audioChunks.reduce((a, c) => { const n = new Float32Array(a.length + c.length); n.set(a); n.set(c, a.length); return n; }, new Float32Array(0));
    try { audioProc.disconnect(); } catch {}
    try { audioCtx.close(); } catch {}
    try { audioStream.getTracks().forEach(t => t.stop()); } catch {}
    if (!invoke) { showToast("ویس دریافت شد"); return; }
    showToast("در حال تبدیل گفتار به متن...");
    try {
      const wav = encodeWav16(flat, 16000);
      const text = await invoke("voice_transcribe", { wavBytes: Array.from(wav) });
      if (text && text.trim()) { chatInput.value = text.trim(); sendChat(); }
      else showToast("چیزی شنیده نشد — دوباره بگو پدر");
    } catch (e) {
      showToast("خطا در تبدیل ویس: " + String(e).slice(0, 80));
    }
  }
};

/* ---------- pill navigation ---------- */
document.querySelectorAll("#pills .pill").forEach(p => {
  p.onclick = () => {
    document.querySelectorAll("#pills .pill").forEach(x => x.classList.remove("active"));
    p.classList.add("active");
    const v = VIEWS[p.dataset.view];
    if (p.dataset.view === "settings") { openSettings(); return; }
    if (v.live) { renderLivePanel(v.live); return; }
    if (v.body) { $("panelTitle").textContent = v.title; $("panelBody").textContent = v.body; $("panel").classList.remove("hidden"); }
  };
});
$("panelClose").onclick = () => $("panel").classList.add("hidden");

/* ---------- settings + approval-first updater ---------- */
var updaterApi = null;
async function loadUpdater() {
  if (updaterApi || !invoke) return updaterApi;
  try {
    const u = await import("@tauri-apps/plugin-updater");
    const pr = await import("@tauri-apps/plugin-process");
    updaterApi = { check: u.check, relaunch: pr.relaunch };
  } catch (e) { updaterApi = null; }
  return updaterApi;
}
function openSettings() {
  $("panelTitle").textContent = "تنظیمات";
  $("panelBody").innerHTML =
    `<div class="set-row"><b>تم</b><span>دکمه ◐ بالای صفحه — ۱۳ تم، ذخیره خودکار</span></div>
     <div class="set-row"><b>ویس</b><span id="voiceState">در حال بررسی...</span></div>
     <div class="set-row"><b>آپدیت</b><span id="updState">—</span></div>
     <button class="map-close" id="updCheck" style="margin-top:8px">بررسی آپدیت</button>
     <div id="updAction" style="margin-top:10px"></div>`;
  $("panel").classList.remove("hidden");
  voiceEngineReady().then(st => {
    $("voiceState").textContent = st.installed ? "موتور ویس آماده‌ست" : "موتور ویس نصب نیست";
  });
  $("updCheck").onclick = async () => {
    const api = await loadUpdater();
    if (!api) { $("updState").textContent = "آپدیتر در این محیط در دسترس نیست"; return; }
    $("updState").textContent = "در حال بررسی...";
    $("updAction").innerHTML = "";
    let update = null;
    try { update = await api.check(); }
    catch (e) { $("updState").textContent = "خطا در بررسی: " + String(e).slice(0, 90); return; }
    if (!update) { $("updState").textContent = "جدیدترین نسخه نصب است"; return; }
    $("updState").textContent = "نسخه " + update.version + " موجود است";
    $("updAction").innerHTML =
      `<div style="margin-bottom:8px;font-size:13px">${(update.body || "").slice(0, 200)}</div>
       <button class="map-close" id="updGo">دانلود و نصب</button>
       <button class="pill" id="updNo" style="margin-right:8px">فعلاً نه</button>`;
    $("updNo").onclick = () => { $("updAction").innerHTML = ""; $("updState").textContent = "نصب لغو شد"; };
    $("updGo").onclick = async () => {
      $("updState").textContent = "در حال دانلود...";
      $("updAction").innerHTML = "";
      try {
        await update.downloadAndInstall();
        $("updState").textContent = "نصب شد — در حال راه‌اندازی مجدد...";
        await api.relaunch();
      } catch (e) { $("updState").textContent = "خطا در نصب: " + String(e).slice(0, 90); }
    };
  };
}

/* ---------- greeting ---------- */
addBubble("سلام پدر، چطور می‌تونم کمکت کنم؟", "her");
