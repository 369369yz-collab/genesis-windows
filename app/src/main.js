/**
 * GENESIS — VOID app logic.
 * Approved design 2026-10-14. Everything visible is real UI;
 * capability backends wire up in pillar 2 (bridge) — statuses are honest.
 */

'use strict';

/* ---------------- avatar state machine ---------------- */
const CLIPS = {
  idle:        'avatar/void/idle.mp4',
  working:     'avatar/void/working.mp4',
  making:      'avatar/void/making.mp4',
  celebrating: 'avatar/void/celebrating.mp4',
};
const video = document.getElementById('avatar');
let avatarState = 'idle';

function setAvatarState(name) {
  if (!CLIPS[name] || name === avatarState) return;
  avatarState = name;
  video.src = CLIPS[name];
  video.play().catch(function () {});
}

/* ---------------- capability catalogue ----------------
   status: 'live' = works now · 'soon' = needs the bridge (pillar 2) */
const CATS = [
  { id: 'cmd', t: 'فرمان', items: [
    ['گفتگو', 'live'], ['حالت عمیق', 'soon'], ['ایجنت', 'soon'], ['تحقیق عمیق', 'soon'] ] },
  { id: 'conn', t: 'کانکتورها', items: [
    ['Gmail', 'soon'], ['Google Drive', 'soon'], ['Calendar', 'soon'], ['GitHub', 'soon'],
    ['Instagram', 'soon'], ['YouTube', 'soon'], ['Spotify', 'soon'], ['Notion', 'soon'], ['Slack', 'soon'] ] },
  { id: 'wire', t: 'سیم خبری', items: [
    ['خبر فوری', 'soon'], ['گیم', 'soon'], ['سینما', 'soon'], ['تکنولوژی', 'soon'], ['تریاژ', 'soon'] ] },
  { id: 'studio', t: 'استودیو', items: [
    ['ریل', 'soon'], ['کاروسل', 'soon'], ['کاور', 'soon'], ['کپشن', 'soon'],
    ['تامبنیل', 'soon'], ['موشن‌گرافیک', 'soon'], ['زیرنویس', 'soon'], ['پژوهش آرت', 'soon'] ] },
  { id: 'comms', t: 'ارتباطات', items: [
    ['دایرکت اینستاگرام', 'soon'], ['کامنت‌ها', 'soon'], ['مسنجر', 'soon'], ['فانل', 'soon'] ] },
  { id: 'sched', t: 'زمان‌بندی', items: [
    ['کرون', 'soon'], ['یادآور', 'soon'], ['دایجست', 'soon'], ['تقویم', 'soon'] ] },
  { id: 'lib', t: 'کتابخانه', items: [
    ['فایل', 'soon'], ['مدیا', 'soon'], ['اسناد', 'soon'], ['آرشیو درایو', 'soon'] ] },
  { id: 'mind', t: 'حافظه و دانش', items: [
    ['خاطرات', 'soon'], ['دانشنامه', 'soon'], ['قوانین', 'soon'], ['دانشگاه', 'soon'], ['جستجوی دانش', 'soon'] ] },
  { id: 'analytics', t: 'تحلیل', items: [
    ['اینسایت اینستاگرام', 'soon'], ['آنالیتیکس یوتیوب', 'soon'], ['KPI', 'soon'], ['رادار ترند', 'soon'], ['هایپ‌سنج', 'soon'] ] },
  { id: 'income', t: 'درآمد', items: [
    ['مسیرهای درآمدی', 'soon'], ['پکیج‌های جنسیس', 'soon'], ['کیف پول', 'soon'], ['گزارش درآمد', 'soon'] ] },
  { id: 'goals', t: 'اهداف', items: [
    ['اهداف فعال', 'soon'], ['پیشرفت', 'soon'], ['زیراهداف', 'soon'] ] },
  { id: 'research', t: 'تحقیق', items: [
    ['تحقیق عمیق', 'soon'], ['وب', 'soon'], ['بازار', 'soon'] ] },
  { id: 'sys', t: 'سیستم', items: [
    ['اتصال شبکه', 'soon'], ['نگهبانان', 'soon'], ['کمیته حقیقت', 'soon'], ['دیسک', 'soon'], ['لاگ‌ها', 'soon'] ] },
];

const QUICK = ['گفتگو', 'کانکتورها', 'سیم خبری', 'استودیو', 'حافظه و دانش', 'درآمد', 'اهداف', 'تحقیق'];

/* ---------------- toast ---------------- */
const toast = document.getElementById('toast');
let toastTimer = null;
function showToast(text) {
  toast.textContent = text;
  toast.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { toast.classList.add('hidden'); }, 2600);
}

/* ---------------- quick options ---------------- */
const optsEl = document.getElementById('opts');
function findCatByLabel(label) {
  if (label === 'گفتگو') return CATS[0];
  return CATS.find(function (c) { return c.t === label; });
}
QUICK.forEach(function (label) {
  const b = document.createElement('button');
  b.className = 'opt';
  b.textContent = label;
  b.addEventListener('click', function () {
    const cat = findCatByLabel(label);
    if (cat) openPanel(cat);
  });
  optsEl.appendChild(b);
});

/* ---------------- world map ---------------- */
const worldMap = document.getElementById('worldMap');
const mapGrid = document.getElementById('mapGrid');
CATS.forEach(function (cat) {
  const div = document.createElement('div');
  div.className = 'map-cat';
  const h = document.createElement('h3');
  h.textContent = cat.t;
  div.appendChild(h);
  cat.items.forEach(function (it) {
    const b = document.createElement('button');
    b.className = 'map-item';
    b.innerHTML = it[0] + (it[1] === 'soon' ? '<span class="soon">به‌زودی</span>' : '');
    b.addEventListener('click', function () { onItemTap(cat, it[0], it[1]); });
    div.appendChild(b);
  });
  mapGrid.appendChild(div);
});
document.getElementById('worldBtn').addEventListener('click', function () {
  worldMap.classList.remove('hidden');
});
document.getElementById('mapClose').addEventListener('click', function () {
  worldMap.classList.add('hidden');
});

/* ---------------- panel ---------------- */
const panel = document.getElementById('panel');
const panelTitle = document.getElementById('panelTitle');
const panelBody = document.getElementById('panelBody');
function openPanel(cat) {
  panelTitle.textContent = cat.t;
  panelBody.innerHTML = '';
  cat.items.forEach(function (it) {
    const row = document.createElement('div');
    row.className = 'panel-row';
    const name = document.createElement('span');
    name.textContent = it[0];
    const st = document.createElement('span');
    st.className = 'st ' + it[1];
    st.textContent = it[1] === 'live' ? 'فعال' : 'به‌زودی';
    row.appendChild(name);
    row.appendChild(st);
    row.style.cursor = 'pointer';
    row.addEventListener('click', function () { onItemTap(cat, it[0], it[1]); });
    panelBody.appendChild(row);
  });
  const note = document.createElement('div');
  note.className = 'panel-note';
  note.textContent = 'پل مغز (ستون ۲) که ساخته بشه، همه‌ی این‌ها یکی‌یکی واقعی وصل میشن — هیچ‌کدوم نمایشی نمی‌مونه.';
  panelBody.appendChild(note);
  panel.classList.remove('hidden');
}
document.getElementById('panelClose').addEventListener('click', function () {
  panel.classList.add('hidden');
});

function onItemTap(cat, label, status) {
  if (status === 'live' && label === 'گفتگو') {
    panel.classList.add('hidden');
    worldMap.classList.add('hidden');
    document.getElementById('chatInput').focus();
    return;
  }
  showToast(label + ' — با ساخته شدن پل مغز وصل میشه');
}

/* ---------------- chat (honest stub until bridge) ---------------- */
const chatLog = document.getElementById('chatLog');
const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');

function addMsg(text, who) {
  const d = document.createElement('div');
  d.className = 'm ' + who;
  d.textContent = text;
  chatLog.appendChild(d);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function sendChat() {
  const text = chatInput.value.trim();
  if (!text) return;
  addMsg(text, 'me');
  chatInput.value = '';
  setAvatarState('working');
  setTimeout(function () {
    addMsg('گرفتم پدر. مغزم (پل ستون ۲) هنوز داره ساخته میشه — به‌زودی جواب واقعی میدم.', 'her');
    setAvatarState('idle');
  }, 1200);
}
sendBtn.addEventListener('click', sendChat);
chatInput.addEventListener('keydown', function (e) {
  if (e.key === 'Enter') sendChat();
});

/* Esc closes overlays */
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') {
    worldMap.classList.add('hidden');
    panel.classList.add('hidden');
  }
});
