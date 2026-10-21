          // COMPLETE 1.0.0 driver = humanflow-drive.js + guardian evidence:
          // (c) boot-PROGRESS screenshot with a visible % during model verify,
          // (b) DRAG proof (window bounds before vs after a topbar drag),
          // (a) CLOSE proof (click the new x control; the WORKFLOW then
          //     asserts at OS level that the app process is gone),
          // (f) real model reply — stub string is FAIL (inherited verbatim).
          const { chromium } = require('playwright-core');
          const sharp = require('sharp');
          const fs = require('fs');
          const path = require('path');
          const OUT = process.env.HF_OUT;
          const CDP = 'http://127.0.0.1:9222';
          const steps = [];
          function step(name, ok, detail) {
            steps.push({ name: name, ok: !!ok, detail: detail || '' });
            console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail ? ' -- ' + detail : ''));
            if (!ok) throw new Error('HUMANFLOW-RED: ' + name + (detail ? ' -- ' + detail : ''));
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
          // H9pre: wait for the brain to be ready BEFORE sending chat.
          // brain.rs boot order: model download+verify -> llama-server spawn
          // -> wait /health. Typing while the model is still downloading makes
          // chat_send fail-closed (honest error bubble) and no real reply can
          // ever appear -- that is what killed run 38752043151 (600s timeout).
          async function waitForBrain(timeoutMs) {
            const http = require('http');
            const t0 = Date.now();
            for (;;) {
              const ok = await new Promise(function (res) {
                const req = http.get('http://127.0.0.1:8080/health', function (r) {
                  r.resume();
                  res(r.statusCode === 200);
                });
                req.on('error', function () { res(false); });
                req.setTimeout(5000, function () { req.destroy(); res(false); });
              });
              if (ok) { console.log('brain ready: llama-server /health 200'); return; }
              const elMin = ((Date.now() - t0) / 60000).toFixed(1);
              if (Date.now() - t0 > timeoutMs) {
                throw new Error('H9pre: brain not ready in ' + (timeoutMs / 60000) + ' min (llama-server /health never 200)');
              }
              console.log('waiting for brain... ' + elMin + ' min elapsed');
              await new Promise(function (r) { setTimeout(r, 15000); });
            }
          }
          (async () => {
            let browser = null;
            for (let i = 0; i < 30 && !browser; i++) {
              try { browser = await chromium.connectOverCDP(CDP); }
              catch (e) { await new Promise(function (r) { setTimeout(r, 2000); }); }
            }
            step('connectOverCDP', !!browser, 'to ' + CDP);
            const pages = browser.contexts().flatMap(function (c) { return c.pages(); })
              .filter(function (p) { return p.url().indexOf('devtools://') !== 0; });
            console.log('pages: ' + pages.map(function (p) { return p.url(); }).join(' | '));
            step('app page found', pages.length > 0, pages.length + ' page(s)');
            const page = pages[0];

            const chatInput = page.locator('#chatInput');
            await chatInput.waitFor({ state: 'visible', timeout: 30000 });
            step('chat input visible (window rendered)', true);
            await nonBlankShot(page, '01-launch.png');

            // (c) PROGRESS proof: catch the boot bar mid-verify with a
            // visible percent and screenshot it. First boot hashes the
            // embedded 5.85 GB model — the bar must show state + %.
            const proofs = { progress: null, drag: null, close: null };
            {
              let captured = null;
              for (let i = 0; i < 225 && !captured; i++) { // up to ~90 s
                const st = await page.evaluate(() => {
                  const bar = document.getElementById('bootBar');
                  if (!bar || bar.classList.contains('hidden')) return null;
                  const pct = (document.getElementById('bootPct') || {}).textContent || '';
                  const label = (document.getElementById('bootLabel') || {}).textContent || '';
                  return { pct: pct, label: label };
                }).catch(() => null);
                if (st && /\d/.test(st.pct)) {
                  await page.screenshot({ path: path.join(OUT, '00-boot-progress.png') });
                  captured = st;
                } else {
                  await new Promise(function (r) { setTimeout(r, 400); });
                }
              }
              step('boot progress % captured on screenshot', !!captured,
                   captured ? ('label="' + captured.label + '" pct="' + captured.pct + '"') : 'boot bar never showed a percent');
              proofs.progress = captured;
            }

            // theme button: open + close picker
            await page.locator('#themeBtn').click();
            await page.locator('#themePicker:not(.hidden)').waitFor({ timeout: 10000 });
            step('theme button opens picker', true);
            await nonBlankShot(page, '02-theme-picker.png');
            await page.locator('#themeClose').click();
            await page.locator('#themePicker').waitFor({ state: 'hidden', timeout: 10000 });
            step('theme picker closes', true);

            // every pill button
            const pills = await page.locator('.pill').all();
            step('five pills present', pills.length === 5, 'found ' + pills.length);
            for (let i = 0; i < pills.length; i++) {
              const label = await pills[i].innerText();
              const view = await pills[i].getAttribute('data-view');
              await pills[i].click();
              if (view === 'chat') {
                // chat pill has no panel body: it just activates
                await page.locator('.pill[data-view="chat"].active').waitFor({ timeout: 10000 });
                step('pill "' + label + '" activates (no panel by design)', true);
              } else {
                await page.locator('#panel:not(.hidden)').waitFor({ timeout: 10000 });
                const title = await page.locator('#panelTitle').innerText();
                step('pill "' + label + '" opens panel', title.trim().length > 0, 'title="' + title.trim() + '"');
                await nonBlankShot(page, '03-pill-' + i + '.png');
                await page.locator('#panelClose').click();
                await page.locator('#panel').waitFor({ state: 'hidden', timeout: 10000 });
              }
            }
            step('all pill buttons exercised', true);

            // (b) DRAG proof: window bounds before vs after a real topbar
            // drag (CDP Browser.getWindowForTarget + mouse drag on the
            // data-tauri-drag-region header). Bounds MUST move.
            {
              const sess = await browser.newBrowserCDPSession();
              const targets = await sess.send('Target.getTargets');
              const t = targets.targetInfos.find(function (x) { return x.type === 'page'; });
              const before = (await sess.send('Browser.getWindowForTarget', { targetId: t.targetId })).bounds;
              await page.mouse.move(240, 18);
              await page.mouse.down();
              await page.mouse.move(380, 88, { steps: 12 });
              await page.mouse.up();
              await new Promise(function (r) { setTimeout(r, 800); });
              const after = (await sess.send('Browser.getWindowForTarget', { targetId: t.targetId })).bounds;
              const dx = after.left - before.left, dy = after.top - before.top;
              proofs.drag = { before: before, after: after, dx: dx, dy: dy };
              step('drag moves window (bounds before vs after)', Math.abs(dx) + Math.abs(dy) >= 20,
                   'dx=' + dx + ' dy=' + dy + ' before=(' + before.left + ',' + before.top + ') after=(' + after.left + ',' + after.top + ')');
              await nonBlankShot(page, '03b-after-drag.png');
            }

            // wait for the brain (model download+verify+load) before chatting;
            // without this, chat_send fails closed while the model downloads
            await waitForBrain(1800000);
            step('brain ready (llama-server /health 200)', true);

            // type + Enter
            const msg1 = 'تست human-flow 123';
            const STUB = 'دارم روش کار می‌کنم';
            await chatInput.fill(msg1);
            await chatInput.press('Enter');
            await page.locator('#chatLog').getByText(msg1).waitFor({ timeout: 10000 });
            step('typed message appears in chat log (Enter path)', true, '"' + msg1 + '"');
            // H9a: REAL model reply (no stub). The canned text must never appear.
            const herBefore1 = await page.locator('#chatLog .bubble.her:not(.error)').count();
            await page.waitForFunction(
              (n) => document.querySelectorAll('#chatLog .bubble.her:not(.error)').length > n,
              herBefore1, { timeout: 600000 });
            const reply1 = ((await page.locator('#chatLog .bubble.her:not(.error)').last().textContent()) || '').trim();
            if (!reply1) throw new Error('H9a: empty model reply');
            if (reply1.includes(STUB)) throw new Error('H9a: STUB REPLY DETECTED — canned text leaked');
            step('real model reply received (no stub)', true, '"' + reply1.slice(0, 120) + '"');
            await nonBlankShot(page, '04-chat-enter.png');

            // send-button path
            const msg2 = 'پیام دوم';
            await chatInput.fill(msg2);
            await page.locator('#sendBtn').click();
            await page.locator('#chatLog').getByText(msg2).waitFor({ timeout: 10000 });
            step('send button delivers message', true, '"' + msg2 + '"');
            await nonBlankShot(page, '05-chat-sendbtn.png');

            // H9: REAL model reply (no stub). The canned text must never appear.
            await page.locator('#chatLog').getByText(msg2).waitFor({ timeout: 10000 });
            const herBefore = await page.locator('#chatLog .bubble.her:not(.error)').count();
            await page.waitForFunction(
              (n) => document.querySelectorAll('#chatLog .bubble.her:not(.error)').length > n,
              herBefore, { timeout: 600000 });
            const replyText = ((await page.locator('#chatLog .bubble.her:not(.error)').last().textContent()) || '').trim();
            if (!replyText) throw new Error('H9: empty model reply');
            if (replyText.includes(STUB)) throw new Error('H9: STUB REPLY DETECTED — canned text leaked');
            step('real model reply received (no stub)', true, '"' + replyText.slice(0, 120) + '"');
            await nonBlankShot(page, '06-chat-reply.png');

            // (a) CLOSE proof: click the new x control for real. The
            // workflow asserts at OS level that the app PROCESS is gone
            // afterwards (not hidden, not minimized — gone).
            await page.locator('#closeBtn').click();
            proofs.close = { clicked: true, at: new Date().toISOString() };
            step('close control clicked', true, proofs.close.at);
            await new Promise(function (r) { setTimeout(r, 2500); });

            fs.writeFileSync(path.join(OUT, 'verdict.json'), JSON.stringify({ pass: true, steps: steps, proofs: proofs }, null, 2));
            fs.writeFileSync(path.join(OUT, 'complete_proofs.json'), JSON.stringify(proofs, null, 2));
            console.log('HUMANFLOW-VERDICT: PASS');
            try { await browser.close(); } catch (e) { /* app already gone — that is the proof working */ }
          })().catch(async function (e) {
            // On failure, capture the chat DOM state: error bubbles tell us
            // whether chat_send errored (and what it said) vs hung silently.
            var chatState = null;
            try {
              chatState = {
                errorBubbles: [],
                herCount: 0,
                typingVisible: false
              };
            } catch (_) {}
            try {
              var eb = page.locator('#chatLog .bubble.her.error');
              var n = 0;
              try { n = await eb.count(); } catch (_) {}
              for (var i = 0; i < n; i++) {
                try { chatState.errorBubbles.push(((await eb.nth(i).textContent()) || '').trim().slice(0, 300)); } catch (_) {}
              }
              try { chatState.herCount = await page.locator('#chatLog .bubble.her').count(); } catch (_) {}
              try { chatState.typingVisible = await page.locator('#typing:not(.hidden)').count() > 0; } catch (_) {}
              try { await page.screenshot({ path: path.join(OUT || '.', '07-chat-fail-state.png') }); } catch (_) {}
            } catch (_) {}
            try { fs.writeFileSync(path.join(OUT || '.', 'verdict.json'), JSON.stringify({ pass: false, error: String((e && e.message) || e), steps: steps, chatState: chatState }, null, 2)); } catch (_) {}
            console.error('HUMANFLOW-VERDICT: FAIL -- ' + ((e && e.message) || e));
            process.exit(1);
          });
