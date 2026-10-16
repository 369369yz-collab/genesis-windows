// GENESIS exhaust-validation CDP driver — zero tolerance.
// Phases via EXH_PHASE env: phase1 | phase2 | phase3 | phase4a | phase4b | phase5
// Fail-closed: any failed step throws => verdict pass=false, job goes RED.
const { chromium } = require('playwright-core');
const sharp = require('sharp');
const fs = require('fs');
const path = require('path');
const OUT = process.env.EXH_OUT;
const CDP = 'http://127.0.0.1:9222';
const PHASE = process.env.EXH_PHASE;
const STUB = 'دارم روش کار می‌کنم';
const THEMES = ["deep-purple","ocean-night","neon-sunset","misty-forest","desert-dawn","polar-ice","night-blood","galaxy","rose-gold","emerald","gray-storm","blossom","chrome-midnight"];
const steps = [];
function step(name, ok, detail) {
  steps.push({ name: name, ok: !!ok, detail: detail || '' });
  console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail ? ' -- ' + detail : ''));
  if (!ok) throw new Error('EXHAUST-RED [' + PHASE + ']: ' + name + (detail ? ' -- ' + detail : ''));
}
async function nonBlankShot(page, file) {
  const p = path.join(OUT, file);
  await page.screenshot({ path: p });
  const st = fs.statSync(p);
  const r = await sharp(p).grayscale().raw().toBuffer({ resolveWithObject: true });
  const d = r.data, n = d.length;
  let sum = 0, sum2 = 0;
  for (let i = 0; i < n; i++) { const v = d[i]; sum += v; sum2 += v * v; }
  const mean = sum / n, sd = Math.sqrt(sum2 / n - mean * mean);
  step('screenshot ' + file + ' non-blank', st.size > 15000 && sd > 4.0,
       'bytes=' + st.size + ' sd=' + sd.toFixed(1));
}
async function waitForBrain(timeoutMs) {
  const http = require('http');
  const t0 = Date.now();
  for (;;) {
    const ok = await new Promise(function (res) {
      const req = http.get('http://127.0.0.1:8080/health', function (r) {
        r.resume(); res(r.statusCode === 200);
      });
      req.on('error', function () { res(false); });
      req.setTimeout(5000, function () { req.destroy(); res(false); });
    });
    if (ok) { console.log('brain ready: llama-server /health 200'); return; }
    if (Date.now() - t0 > timeoutMs) throw new Error('brain not ready in ' + (timeoutMs / 60000) + ' min');
    console.log('waiting for brain... ' + (((Date.now() - t0) / 60000).toFixed(1)) + ' min elapsed');
    await new Promise(function (r) { setTimeout(r, 15000); });
  }
}
async function connectPage() {
  let browser = null;
  for (let i = 0; i < 30 && !browser; i++) {
    try { browser = await chromium.connectOverCDP(CDP); }
    catch (e) { await new Promise(function (r) { setTimeout(r, 2000); }); }
  }
  step('connectOverCDP', !!browser, 'to ' + CDP);
  const pages = browser.contexts().flatMap(function (c) { return c.pages(); })
    .filter(function (p) { return p.url().indexOf('devtools://') !== 0; });
  step('app page found', pages.length > 0, pages.length + ' page(s)');
  return { browser: browser, page: pages[0] };
}
function herSel() { return '#chatLog .bubble.her:not(.error)'; }
async function awaitHerReply(page, before, timeoutMs, label) {
  await page.waitForFunction(
    function (n) { return document.querySelectorAll('#chatLog .bubble.her:not(.error)').length > n; },
    before, { timeout: timeoutMs });
  const t = ((await page.locator(herSel()).last().textContent()) || '').trim();
  if (!t) throw new Error(label + ': empty model reply');
  if (t.includes(STUB)) throw new Error(label + ': STUB REPLY DETECTED — canned text leaked');
  step('real model reply (' + label + ', no stub)', true, '"' + t.slice(0, 100) + '"');
  return t;
}
async function sendVia(page, text, via) {
  const input = page.locator('#chatInput');
  await input.fill(text);
  if (via === 'enter') await input.press('Enter');
  else await page.locator('#sendBtn').click();
  await page.locator('#chatLog').getByText(text.slice(0, 40)).waitFor({ timeout: 15000 });
}

async function phase1(page) {
  const input = page.locator('#chatInput');
  await input.waitFor({ state: 'visible', timeout: 30000 });
  step('chat input visible (window rendered)', true);
  const greet = await page.locator(herSel()).count();
  step('greeting bubble present on launch', greet >= 1, 'her bubbles=' + greet);
  await nonBlankShot(page, '01-launch.png');

  // 5 pills
  const pills = await page.locator('.pill').all();
  step('five pills present', pills.length === 5, 'found ' + pills.length);
  const panelViews = ['world369', 'nexus', 'gates'];
  for (const v of panelViews) {
    await page.locator('.pill[data-view="' + v + '"]').click();
    await page.locator('#panel:not(.hidden)').waitFor({ timeout: 10000 });
    const title = (await page.locator('#panelTitle').innerText()).trim();
    const body = (await page.locator('#panelBody').innerText()).trim();
    step('pill "' + v + '" opens panel', title.length > 0 && body.length > 0, 'title="' + title + '" bodyLen=' + body.length);
    await nonBlankShot(page, '02-pill-' + v + '.png');
    await page.locator('#panelClose').click();
    await page.locator('#panel').waitFor({ state: 'hidden', timeout: 10000 });
  }
  await page.locator('.pill[data-view="chat"]').click();
  await page.locator('.pill[data-view="chat"].active').waitFor({ timeout: 10000 });
  step('pill "chat" activates', true);
  await page.locator('.pill[data-view="settings"]').click();
  await page.locator('#panel:not(.hidden)').waitFor({ timeout: 10000 });
  const st = (await page.locator('#panelTitle').innerText()).trim();
  const updBtn = await page.locator('#updCheck').count();
  step('pill "settings" opens settings panel', st === 'تنظیمات' && updBtn === 1, 'title="' + st + '" updCheck=' + updBtn);
  await nonBlankShot(page, '02-pill-settings.png');
  await page.locator('#panelClose').click();
  await page.locator('#panel').waitFor({ state: 'hidden', timeout: 10000 });
  step('all 5 pills exercised', true);

  // 13 themes
  await page.locator('#themeBtn').click();
  await page.locator('#themePicker:not(.hidden)').waitFor({ timeout: 10000 });
  const swatches = await page.locator('.theme-swatch').all();
  step('13 theme swatches present', swatches.length === 13, 'found ' + swatches.length);
  const order = THEMES.slice();
  order.splice(order.indexOf('night-blood'), 1); order.push('night-blood'); // end on night-blood
  for (const id of order) {
    await page.locator('.theme-swatch[data-theme="' + id + '"]').click();
    const applied = await page.evaluate(function () { return document.body.dataset.theme; });
    const current = await page.locator('.theme-swatch[data-theme="' + id + '"].current').count();
    const toast = (await page.locator('#toast').textContent()) || '';
    step('theme "' + id + '" applies cleanly', applied === id && current === 1 && toast.indexOf('فعال شد') >= 0,
         'body=' + applied + ' current=' + current + ' toast="' + toast.slice(0, 30) + '"');
    await nonBlankShot(page, '03-theme-' + id + '.png');
  }
  await page.locator('#themeClose').click();
  await page.locator('#themePicker').waitFor({ state: 'hidden', timeout: 10000 });
  const saved = await page.evaluate(function () { return localStorage.getItem('genesis-theme'); });
  step('theme persisted to localStorage', saved === 'night-blood', 'saved=' + saved);
  step('13/13 themes applied, no mixed-theme artifacts', true);

  // brain, then chat core paths
  await waitForBrain(1800000);
  step('brain ready (llama-server /health 200)', true);

  const m1 = 'تست exhaust یک';
  let before = await page.locator(herSel()).count();
  await sendVia(page, m1, 'enter');
  step('Enter path delivers message', true, '"' + m1 + '"');
  await awaitHerReply(page, before, 600000, 'enter');
  await nonBlankShot(page, '04-chat-enter.png');

  const m2 = 'پیام دوم exhaust';
  before = await page.locator(herSel()).count();
  await sendVia(page, m2, 'button');
  step('send-button path delivers message', true, '"' + m2 + '"');
  await awaitHerReply(page, before, 600000, 'send-button');
  await nonBlankShot(page, '05-chat-sendbtn.png');

  const mLong = 'متن طولانی exhaust: ' + 'تست '.repeat(400); // ~2000 chars
  before = await page.locator(herSel()).count();
  await sendVia(page, mLong, 'enter');
  step('long message delivered (' + mLong.length + ' chars)', true);
  await awaitHerReply(page, before, 900000, 'long-message');
  await nonBlankShot(page, '06-chat-long.png');

  // empty + whitespace must not crash, must not send
  const meBefore = await page.locator('#chatLog .bubble.me').count();
  const errBefore = await page.locator('#chatLog .bubble.her.error').count();
  await input.fill('');
  await input.press('Enter');
  await new Promise(function (r) { setTimeout(r, 2500); });
  await input.fill('   ');
  await input.press('Enter');
  await new Promise(function (r) { setTimeout(r, 2500); });
  const meAfter = await page.locator('#chatLog .bubble.me').count();
  const errAfter = await page.locator('#chatLog .bubble.her.error').count();
  const inputAlive = await input.isVisible();
  step('empty/whitespace message: no crash, no send', meAfter === meBefore && errAfter === errBefore && inputAlive,
       'me=' + meBefore + '->' + meAfter + ' err=' + errBefore + '->' + errAfter);
  await nonBlankShot(page, '07-chat-empty.png');

  const mMix = 'Hello پدر — how are you امروز؟ test 123';
  before = await page.locator(herSel()).count();
  await sendVia(page, mMix, 'enter');
  step('Persian+English mixed message delivered', true, '"' + mMix + '"');
  await awaitHerReply(page, before, 600000, 'mixed');
  await nonBlankShot(page, '08-chat-mixed.png');

  const m3 = 'یه سوال دیگه پدر';
  before = await page.locator(herSel()).count();
  await sendVia(page, m3, 'enter');
  step('consecutive exchange delivered', true, '"' + m3 + '"');
  await awaitHerReply(page, before, 600000, 'consecutive');
  await nonBlankShot(page, '09-chat-second.png');

  fs.writeFileSync(path.join(OUT, 'markers.json'), JSON.stringify({ p1_msg: m1, theme: 'night-blood' }));
  step('phase1 complete: pills/themes/chat-core all green', true);
}

async function phase2(page) {
  // voice honest-degrade
  await page.locator('#micBtn').click();
  await new Promise(function (r) { setTimeout(r, 1800); });
  const toast = ((await page.locator('#toast').textContent()) || '').trim();
  const fake = toast.indexOf('در حال گوش دادن') >= 0 || toast.indexOf('در حال تبدیل گفتار') >= 0;
  const honest = toast.indexOf('موتور ویس هنوز نصب نیست') >= 0 || toast.indexOf('دسترسی به میکروفون داده نشد') >= 0;
  step('voice honest-degrade (no fake success)', !fake && honest, 'toast="' + toast.slice(0, 60) + '"');
  await nonBlankShot(page, '10-voice.png');

  // settings panel
  await page.locator('.pill[data-view="settings"]').click();
  await page.locator('#panel:not(.hidden)').waitFor({ timeout: 10000 });
  const title = (await page.locator('#panelTitle').innerText()).trim();
  const rows = await page.locator('#panelBody .set-row').count();
  const voiceState = ((await page.locator('#voiceState').textContent()) || '').trim();
  step('settings panel opens with all rows', title === 'تنظیمات' && rows >= 3,
       'title="' + title + '" rows=' + rows + ' voiceState="' + voiceState.slice(0, 40) + '"');
  const voiceHonest = voiceState.indexOf('نصب نیست') >= 0 || voiceState.indexOf('آماده') >= 0;
  step('settings voice state honest', voiceHonest, '"' + voiceState.slice(0, 50) + '"');
  step('settings updCheck button present', await page.locator('#updCheck').count() === 1);
  await nonBlankShot(page, '11-settings.png');

  // updater approval-first
  await page.locator('#updCheck').click();
  await page.waitForFunction(function () {
    const el = document.querySelector('#updState');
    return el && el.textContent.trim() !== '—' && el.textContent.trim() !== 'در حال بررسی...';
  }, null, { timeout: 120000 });
  const updState = ((await page.locator('#updState').textContent()) || '').trim();
  const updGo = await page.locator('#updGo').count();
  const updNo = await page.locator('#updNo').count();
  const autoDl = updState.indexOf('در حال دانلود') >= 0 && updGo === 0;
  if (updState.indexOf('جدیدترین نسخه نصب است') >= 0) {
    step('updater: up-to-date reported honestly', true, '"' + updState.slice(0, 50) + '"');
  } else if (updState.indexOf('موجود است') >= 0 && updGo === 1 && updNo === 1) {
    step('updater: available version shown with approval buttons (no auto-download)', !autoDl,
         '"' + updState.slice(0, 50) + '"');
    await page.locator('#updNo').click();
    await page.waitForFunction(function () {
      return document.querySelector('#updState').textContent.indexOf('لغو شد') >= 0;
    }, null, { timeout: 10000 });
    step('updater: decline path honest ("نصب لغو شد", no download)', true);
  } else if (updState.indexOf('در دسترس نیست') >= 0 || updState.indexOf('خطا در بررسی') >= 0) {
    step('updater: honest boundary state (no fake update)', true, '"' + updState.slice(0, 60) + '"');
  } else {
    step('updater: unexpected state', false, '"' + updState.slice(0, 80) + '"');
  }
  step('updater: no auto-download without consent', !autoDl, 'autoDl=' + autoDl);
  await nonBlankShot(page, '12-updater.png');
  await page.locator('#panelClose').click();
  await page.locator('#panel').waitFor({ state: 'hidden', timeout: 10000 });
  step('phase2 complete: voice/settings/updater all green', true);
}

async function phase3(page) {
  const markers = JSON.parse(fs.readFileSync(path.join(OUT, 'markers.json'), 'utf8'));
  await page.locator('#chatLog').getByText(markers.p1_msg).waitFor({ timeout: 30000 });
  step('chat history survived restart', true, 'found "' + markers.p1_msg + '"');
  const theme = await page.evaluate(function () { return document.body.dataset.theme; });
  step('saved theme survived restart', theme === markers.theme, 'body theme=' + theme);
  await nonBlankShot(page, '12b-persist.png');

  // rapid-fire 5 messages
  const before = await page.locator(herSel()).count();
  const msgs = ['rapid یک', 'rapid دو', 'rapid سه', 'rapid چهار', 'rapid پنج'];
  const input = page.locator('#chatInput');
  for (const m of msgs) {
    await input.fill(m);
    await input.press('Enter');
    await new Promise(function (r) { setTimeout(r, 400); });
  }
  step('rapid-fire: 5 messages sent in a row', true);
  await page.waitForFunction(function (n) {
    return document.querySelectorAll('#chatLog .bubble.her:not(.error)').length >= n;
  }, before + 5, { timeout: 1500000 });
  const errCount = await page.locator('#chatLog .bubble.her.error').count();
  step('rapid-fire: 5 real replies, no error bubbles', errCount === 0, 'errorBubbles=' + errCount);
  const newReplies = await page.locator(herSel()).all();
  let stubFound = false, emptyFound = false;
  for (let i = before; i < newReplies.length; i++) {
    const t = ((await newReplies[i].textContent()) || '').trim();
    if (!t) emptyFound = true;
    if (t.includes(STUB)) stubFound = true;
  }
  step('rapid-fire: replies real, no stub, none empty', !stubFound && !emptyFound,
       'stub=' + stubFound + ' empty=' + emptyFound);
  await nonBlankShot(page, '13-rapidfire.png');
  step('phase3 complete: persistence + rapid-fire green', true);
}

async function phase4a(page) {
  const m = 'پیام وسط ری‌استارت';
  await page.locator('#chatInput').fill(m);
  await page.locator('#chatInput').press('Enter');
  await page.locator('#chatLog').getByText(m).waitFor({ timeout: 15000 });
  step('mid-chat message sent', true, '"' + m + '"');
  await page.waitForFunction(function () {
    const t = document.querySelector('#typing');
    return t && !t.classList.contains('hidden');
  }, null, { timeout: 180000 });
  step('reply in flight (typing visible) — killing now', true);
  await nonBlankShot(page, '14-midchat.png');
  fs.writeFileSync(path.join(OUT, 'MIDCHAT'), 'kill-now');
}

async function phase4b(page) {
  const markers = JSON.parse(fs.readFileSync(path.join(OUT, 'markers.json'), 'utf8'));
  await page.locator('#chatLog').getByText(markers.p1_msg).waitFor({ timeout: 30000 });
  step('history intact after mid-chat kill', true, 'found "' + markers.p1_msg + '"');
  await page.locator('#chatInput').waitFor({ state: 'visible', timeout: 30000 });
  step('app responsive after mid-chat kill', true);
  const m = 'بعد از ری‌استارت وسط چت';
  const before = await page.locator(herSel()).count();
  await page.locator('#chatInput').fill(m);
  await page.locator('#chatInput').press('Enter');
  await page.locator('#chatLog').getByText(m).waitFor({ timeout: 15000 });
  step('post-kill message delivered', true, '"' + m + '"');
  await awaitHerReply(page, before, 900000, 'post-kill');
  await page.locator('.pill[data-view="chat"]').click();
  await page.locator('.pill[data-view="chat"].active').waitFor({ timeout: 10000 });
  step('pills still functional after kill', true);
  await nonBlankShot(page, '15-recovery.png');
  step('phase4b complete: recovery green', true);
}

async function phase5(page) {
  const input = page.locator('#chatInput');
  await input.waitFor({ state: 'visible', timeout: 30000 });
  step('reinstalled app renders (chat input visible)', true);
  const greet = await page.locator(herSel()).count();
  step('greeting bubble on reinstalled app', greet >= 1, 'her bubbles=' + greet);
  await nonBlankShot(page, '16-reinstall.png');
  step('phase5 complete: reinstall render green', true);
}

(async () => {
  const c = await connectPage();
  const page = c.page;
  try {
    if (PHASE === 'phase1') await phase1(page);
    else if (PHASE === 'phase2') await phase2(page);
    else if (PHASE === 'phase3') await phase3(page);
    else if (PHASE === 'phase4a') await phase4a(page);
    else if (PHASE === 'phase4b') await phase4b(page);
    else if (PHASE === 'phase5') await phase5(page);
    else throw new Error('unknown EXH_PHASE=' + PHASE);
    fs.writeFileSync(path.join(OUT, PHASE + '-verdict.json'), JSON.stringify({ pass: true, steps: steps }, null, 2));
    console.log('EXHAUST ' + PHASE + ': PASS');
  } catch (e) {
    try { await page.screenshot({ path: path.join(OUT, PHASE + '-fail.png') }); } catch (_) {}
    fs.writeFileSync(path.join(OUT, PHASE + '-verdict.json'),
      JSON.stringify({ pass: false, error: String((e && e.message) || e), steps: steps }, null, 2));
    console.error('EXHAUST ' + PHASE + ': FAIL -- ' + ((e && e.message) || e));
    process.exit(1);
  } finally {
    try { await c.browser.close(); } catch (_) {}
  }
})();
