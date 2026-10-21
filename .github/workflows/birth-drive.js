          // GENESIS COMPLETE 1.0.0 — BIRTH TEST driver (guardian evidence e).
          // Exercises EVERY feature of the installed final build in repeated
          // cycles for a real 30-60 minute wall-clock run. Every action is
          // timestamped into birth_log.jsonl the moment it happens; the
          // workflow asserts first->last span >= 30 min. Fail-closed: any
          // failed action aborts RED. The canned stub string anywhere in a
          // reply is FAIL (same law as human-flow).
          const { chromium } = require('playwright-core');
          const fs = require('fs');
          const path = require('path');
          const OUT = process.env.HF_OUT;
          const CDP = 'http://127.0.0.1:9222';
          const TARGET_MIN = parseInt(process.env.BIRTH_TARGET_MIN || '35', 10);
          const STUB = 'دارم روش کار می‌کنم';
          const logPath = path.join(OUT, 'birth_log.jsonl');
          const t0 = Date.now();
          function log(action, ok, detail) {
            const rec = { ts_utc: new Date().toISOString(), elapsed_s: Math.round((Date.now() - t0) / 1000), action: action, ok: !!ok, detail: detail || '' };
            fs.appendFileSync(logPath, JSON.stringify(rec) + '\n');
            console.log((ok ? 'PASS ' : 'FAIL ') + action + (detail ? ' -- ' + detail : ''));
            if (!ok) throw new Error('BIRTH-RED: ' + action + (detail ? ' -- ' + detail : ''));
          }
          async function waitForBrain(timeoutMs) {
            const http = require('http');
            const start = Date.now();
            for (;;) {
              const ok = await new Promise(function (res) {
                const req = http.get('http://127.0.0.1:8080/health', function (r) { r.resume(); res(r.statusCode === 200); });
                req.on('error', function () { res(false); });
                req.setTimeout(5000, function () { req.destroy(); res(false); });
              });
              if (ok) return;
              if (Date.now() - start > timeoutMs) throw new Error('BIRTH-RED: brain never ready');
              await new Promise(function (r) { setTimeout(r, 15000); });
            }
          }
          (async () => {
            let browser = null;
            for (let i = 0; i < 30 && !browser; i++) {
              try { browser = await chromium.connectOverCDP(CDP); }
              catch (e) { await new Promise(function (r) { setTimeout(r, 2000); }); }
            }
            if (!browser) throw new Error('BIRTH-RED: cannot connect CDP');
            const pages = browser.contexts().flatMap(function (c) { return c.pages(); })
              .filter(function (p) { return p.url().indexOf('devtools://') !== 0; });
            if (!pages.length) throw new Error('BIRTH-RED: no app page');
            const splashPage0 = pages.find(function (p) { return p.url().indexOf('splash') !== -1; }) || null;
            const page = pages.filter(function (p) { return p.url().indexOf('splash') === -1; })[0] || pages[0];
            const chatInput = page.locator('#chatInput');
            await chatInput.waitFor({ state: 'visible', timeout: 30000 });
            log('launch + window rendered', true);
            await waitForBrain(1800000);
            log('brain ready (llama /health 200)', true);
            // Splash handover: splash must dismiss itself once the brain
            // is ready (Rust 120 s fail-safe is the backstop). Cycles below
            // exercise the SHOWN main window only.
            if (splashPage0) {
              try { await splashPage0.screenshot({ path: path.join(OUT, 'birth-splash.png') }); } catch (e) {}
              const hT0 = Date.now();
              let gone = false;
              while (!gone && Date.now() - hT0 < 180000) {
                if (splashPage0.isClosed()) { gone = true; break; }
                const still = browser.contexts().flatMap(function (c) { return c.pages(); })
                  .some(function (pg) { return pg.url().indexOf('splash') !== -1; });
                if (!still) { gone = true; break; }
                await new Promise(function (r) { setTimeout(r, 2000); });
              }
              log('splash handover (splash dismissed, main shown)', gone, 'waited ' + Math.round((Date.now() - hT0) / 1000) + 's');
            } else {
              log('splash handover (no splash page at connect; main already sole page)', true);
            }

            const prompts = ['سلام، یک جمله کوتاه درباره امروز بگو',
                             'یک نکته کوتاه درباره بازی‌ها بگو',
                             'حالت چطوره؟ کوتاه جواب بده',
                             'یک جمله انگیزشی کوتاه بگو'];
            let cycle = 0;
            while ((Date.now() - t0) / 60000 < TARGET_MIN) {
              cycle++;
              const msg = prompts[(cycle - 1) % prompts.length] + ' (' + cycle + ')';
              const herBefore = await page.locator('#chatLog .bubble.her:not(.error)').count();
              await chatInput.fill(msg);
              await chatInput.press('Enter');
              await page.locator('#chatLog').getByText(msg).waitFor({ timeout: 10000 });
              log('cycle ' + cycle + ': chat sent (Enter)', true, msg);
              await page.waitForFunction(
                (n) => document.querySelectorAll('#chatLog .bubble.her:not(.error)').length > n,
                herBefore, { timeout: 600000 });
              const reply = ((await page.locator('#chatLog .bubble.her:not(.error)').last().textContent()) || '').trim();
              if (!reply) throw new Error('BIRTH-RED: empty reply cycle ' + cycle);
              if (reply.includes(STUB)) throw new Error('BIRTH-RED: STUB REPLY cycle ' + cycle);
              log('cycle ' + cycle + ': real model reply', true, reply.slice(0, 100));

              const pills = await page.locator('.pill').all();
              for (let i = 0; i < pills.length; i++) {
                const view = await pills[i].getAttribute('data-view');
                await pills[i].click();
                if (view !== 'chat') {
                  await page.locator('#panel:not(.hidden)').waitFor({ timeout: 10000 });
                  await page.locator('#panelClose').click();
                  await page.locator('#panel').waitFor({ state: 'hidden', timeout: 10000 });
                }
              }
              log('cycle ' + cycle + ': all 5 pills + panels exercised', true);

              await page.locator('#themeBtn').click();
              await page.locator('#themePicker:not(.hidden)').waitFor({ timeout: 10000 });
              const swatches = await page.locator('.theme-swatch').all();
              await swatches[cycle % swatches.length].click();
              await page.locator('#themeClose').click();
              await page.locator('#themePicker').waitFor({ state: 'hidden', timeout: 10000 });
              log('cycle ' + cycle + ': theme switched (' + swatches.length + ' themes present)', true);

              await page.screenshot({ path: path.join(OUT, 'birth-cycle-' + String(cycle).padStart(2, '0') + '.png') });
              log('cycle ' + cycle + ': screenshot captured', true);
            }

            // Close through the real control; workflow asserts process death.
            await page.locator('#closeBtn').click();
            log('close control clicked after ' + cycle + ' cycles', true);
            await new Promise(function (r) { setTimeout(r, 2500); });
            const spanMin = ((Date.now() - t0) / 60000).toFixed(1);
            fs.writeFileSync(path.join(OUT, 'birth_verdict.json'),
              JSON.stringify({ pass: true, cycles: cycle, span_min: parseFloat(spanMin) }, null, 2));
            console.log('BIRTH-VERDICT: PASS cycles=' + cycle + ' span_min=' + spanMin);
            try { await browser.close(); } catch (e) { /* app gone — expected */ }
          })().catch(function (e) {
            try { fs.appendFileSync(logPath, JSON.stringify({ ts_utc: new Date().toISOString(), action: 'ABORT', ok: false, detail: String((e && e.message) || e) }) + '\n'); } catch (_) {}
            try { fs.writeFileSync(path.join(OUT, 'birth_verdict.json'), JSON.stringify({ pass: false, error: String((e && e.message) || e) }, null, 2)); } catch (_) {}
            console.error('BIRTH-VERDICT: FAIL -- ' + ((e && e.message) || e));
            process.exit(1);
          });
