# HUMANFLOW GUI DISSECTION — how production teams drive desktop-app GUIs on GitHub windows-latest

Date: 2026-10-15. Purpose: reverse-engineer the real prior art BEFORE designing
`human-flow.yml` (YZ REVERSE-ENGINEERING-BEFORE-BUILD LAW). Question: can we
install → launch → click → type → screenshot the real GENESIS Tauri app on a
GitHub-hosted `windows-latest` runner, honestly?

## 1. The core constraint: is there an interactive desktop on windows-latest?

Findings (multiple independent sources):
- GitHub-hosted Windows runners run the agent as a service, but the image DOES
  provide a usable desktop session for GUI rendering. Evidence:
  - harborline-software/sunfish (a Tauri app, like ours): "your CI runner may not
    have a graphics surface for WebView2. Use a Windows runner with a desktop
    session (`windows-latest` on GitHub Actions works; minimal Server Core images
    don't)." — i.e. windows-latest is explicitly the GOOD case.
  - Microsoft's own `winappCli` docs show "Launch and test in GitHub Actions"
    as a supported scenario.
  - Playwright headed browsers + screenshots are routine on windows-latest.
- What does NOT work there: OS-level input injection on a locked/secure desktop
  (winappCli `click`/`send-keys --via send-input` fail fast with
  `no_interactive_desktop`). So: real mouse/keyboard injection is unreliable;
  in-app automation must go through a non-injecting channel.

Conclusion: a real desktop session exists; pixels render; screenshots are real.
Synthetic OS input is the fragile part — avoid it.

## 2. The production pattern for Tauri-on-Windows GUI testing: CDP + Playwright

This is THE standard approach, used by many production Tauri projects. Dissection
of the pattern (sources: Haprog/tauri-cdp, Haprog/playwright-cdp,
srsholmes/tauri-playwright, thedonmon/tauri-skill, org62/joybug-tauri,
soulaudio/soul-player, Playwright official WebView2 docs):

1. Launch the app with the WebView2-respected env var BEFORE the process starts:
   `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222`
   (PowerShell: `$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=9222"`).
   This is a WebView2 loader feature — NO app code change needed, works on
   release/production builds (Haprog's "debug builds only" note refers to their
   in-code variant, not the externally-set env var).
2. Poll `http://127.0.0.1:9222/json/version` until the webview is up.
   If it never answers, the window never rendered — a genuine, fail-closed signal.
3. `chromium.connectOverCDP('http://127.0.0.1:9222')` from `playwright-core`
   (no browser download needed — we drive the app's OWN WebView2).
   Take `browser.contexts()[0].pages()`, skip `devtools://` targets, use the app page.
4. Full Playwright API against the REAL app DOM: `locator.click()`,
   `locator.fill()`, `keyboard.press('Enter')`, `page.screenshot()`,
   `expect`-style DOM assertions. Playwright's click/fill/type here go through
   CDP Input domain (synthetic but IN-PROCESS to the renderer) — they do NOT
   need the OS interactive desktop, unlike WinAppDriver/PyAutoGUI injection.

Why NOT the alternatives:
- WinAppDriver: needs the driver binary + Appium client, drives via UIA; works
  but heavier, and its screenshot path captures the session desktop (risky on CI).
- FlaUI/AutoIt/PyAutoGUI: OS-level injection — exactly what fails without an
  unlocked interactive desktop (winappCli documents `no_interactive_desktop`).
- winappCli UIA verbs (`invoke`, `set-value`) are headless-friendly but CANNOT
  see inside WebView2 web content reliably (web content needs Chromium
  accessibility tree); CDP sees the real DOM.

## 3. What we assert (and what each assertion honestly proves)

| Step | Assertion | Proves |
|---|---|---|
| CDP endpoint answers | webview process created its renderer | window actually rendered (not a zombie process) |
| `#chatInput` visible | DOM + CSS layout live | UI is not dead/blank |
| screenshot stddev > threshold (sharp) | pixels vary | screenshot is not a black/blank frame |
| click `#themeBtn` → `#themePicker` visible | JS event wiring live | buttons respond |
| click 5 `.pill`s → `#panel` visible, title non-empty | navigation wiring live | every main button works |
| fill `#chatInput` + Enter → bubble in `#chatLog` | keydown handler + DOM update | typing + Enter path works |
| reply bubble appears (~1.2s) | `sendChat()` completed | full interaction loop closed |
| click `#sendBtn` second message | click-to-send path | both send paths work |

Known honest limitations (documented, not hidden):
- `sendChat()` in the CURRENT frontend is a stub: it appends a canned reply
  ("حتماً پدر — دارم روش کار می‌کنم.") after 1.2s without calling the model.
  The human-flow proves UI interactivity, NOT model inference. Real-model chat
  remains B2's job in windows-selftest.yml.
- The test does NOT wait for the 5GB model download (it runs in background,
  as in production first-boot). Run budget stays ~15 min instead of ~40.
- Screenshot "non-blank" gate = pixel stddev via `sharp` on the PNG. Threshold
  (stddev < 4.0 on 0-255 grayscale = blank) is heuristic but measured, and it
  is only ONE of several gates — DOM assertions carry the real proof.
- CDP port 9222 is opened on localhost for the duration of the test only,
  on an ephemeral runner. Acceptable; never shipped to users.

## 4. Design decision (final)

human-flow.yml = install (proven A1/A2 steps copied from windows-selftest.yml)
→ launch with `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222`
→ poll CDP → Playwright (playwright-core + sharp, npm on the runner) drives
clicks/types/screenshots → fail-closed verdict → upload `genesis-humanflow-evidence`.
No app code changes. No input injection. No fakes: if CDP never answers or any
assertion fails, the run goes RED with the exact cause.
