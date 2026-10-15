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

            // type + Enter
            const msg1 = 'تست human-flow 123';
            await chatInput.fill(msg1);
            await chatInput.press('Enter');
            await page.locator('#chatLog').getByText(msg1).waitFor({ timeout: 10000 });
            step('typed message appears in chat log (Enter path)', true, '"' + msg1 + '"');
            await page.getByText('حتماً پدر', { exact: false }).first().waitFor({ timeout: 15000 });
            step('app reply bubble appears', true);
            await nonBlankShot(page, '04-chat-enter.png');

            // send-button path
            const msg2 = 'پیام دوم';
            await chatInput.fill(msg2);
            await page.locator('#sendBtn').click();
            await page.locator('#chatLog').getByText(msg2).waitFor({ timeout: 10000 });
            step('send button delivers message', true, '"' + msg2 + '"');
            await nonBlankShot(page, '05-chat-sendbtn.png');

            // H9: REAL model reply (no stub). The canned text must never appear.
            const STUB = 'دارم روش کار می‌کنم';
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

            fs.writeFileSync(path.join(OUT, 'verdict.json'), JSON.stringify({ pass: true, steps: steps }, null, 2));
            console.log('HUMANFLOW-VERDICT: PASS');
            await browser.close();
          })().catch(function (e) {
            try { fs.writeFileSync(path.join(OUT || '.', 'verdict.json'), JSON.stringify({ pass: false, error: String((e && e.message) || e), steps: steps }, null, 2)); } catch (_) {}
            console.error('HUMANFLOW-VERDICT: FAIL -- ' + ((e && e.message) || e));
            process.exit(1);
          });
