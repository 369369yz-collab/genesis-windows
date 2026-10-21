# UI surface contract — genesis-scheduler

Per `../_contracts/GENESIS_UI_CONTRACT_AVATAR_FIRST.md`: this module is a
backend service. It builds NO panels, NO persistent controls, NO windows of
its own beyond the toast described below. All floating-layer rendering
belongs to the avatar host's summoned-layer renderer (v1.1).

## The one UI surface: reminder toast

| Field | Contract |
|---|---|
| What | A small, auto-dismissing toast carrying the reminder's title + message. |
| When | At the moment a scheduled `reminder` job fires. Nothing else in this module shows UI. |
| Lifetime | Auto-dismisses after 20 seconds (no click required). |
| Identity | Dark + gold bloom/fade when rendered by the avatar host; the interim native Windows popup is a plain system dialog (see below). |
| Actions | None. The toast is informational only — it appears, then goes away. |

## Data contract for the avatar host

When a reminder fires, `recipes/reminder.py` appends ONE JSON line to
`<data-dir>/reminders.log`. That file IS the toast feed. Each line:

```json
{"utc": "2026-10-13T06:30:00+00:00", "title": "drink water",
 "message": "Time to drink water", "shown": true,
 "method": "WScript.Shell.Popup (auto-dismiss 20s)",
 "log": "C:\\Users\\...\\.genesis\\scheduler\\reminders.log"}
```

The avatar host's summoned-layer renderer consumes this feed and renders
the floating toast beside GENESIS (dark + gold, soft bloom/fade,
auto-dismiss). Until that renderer exists, the runner shows the interim
native Windows popup so the reminder is actually seen.

## Interim Windows behavior (until avatar host v1.1)

`recipes/reminder.py` shows a `WScript.Shell.Popup` dialog (info icon,
auto-dismiss after 20s) — stdlib `subprocess` + `wscript`, zero extra
modules. If `wscript` is unavailable it falls back to a blocking
`MessageBoxW` and records that honestly in the log's `method` field.

On non-Windows hosts the runner is log-only (`shown: false`); no fake UI
is pretended.

## What this module will never do

- No settings panel, no job-list window, no tray UI.
- No toast for `morning_news` (it writes a digest file; the daily report
  module owns presenting it) and no toast for plain `command` actions.
- No sound, no always-on-top windows, no stealing focus.
