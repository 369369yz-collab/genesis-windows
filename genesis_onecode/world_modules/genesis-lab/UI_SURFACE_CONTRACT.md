# genesis-lab — UI-surface contract (avatar-first)

Module: genesis-lab v1.0.1. Status: backend service + UI-surface contract.
The module builds NO panels, NO persistent controls, NO buttons of its own.
All floating-layer rendering belongs to the avatar host's summoned-layer
renderer (v1.1 spec). This file declares WHAT the lab offers the renderer,
WHEN it appears, and WHAT actions it carries, per
GENESIS_UI_CONTRACT_AVATAR_FIRST.md.

## Surface: the verdict card
A small floating card that blooms beside the avatar when a lab run completes.

### Trigger (when)
- `run_tests(app_id, test_plan)` completes -> renderer fetches
  `verdict(app_id)` and blooms the card.
- On-demand: father asks "how did the lab test go?" -> renderer shows the
  card for the latest run of that app.
- Never shown for `sandbox_unavailable` / `error` statuses (those are silent
  log lines or spoken summaries, not cards).

### Card content (what)
| Slot | Source (verdict() dict) | Notes |
|---|---|---|
| Accent | `verdict` | PASS = gold, FAIL = red, WARN = amber |
| Title | fixed | "Lab verdict" |
| App | `app_id` | plain text |
| Reason line | `reason` | one short line, e.g. "all 3 test(s) passed in sandbox" |
| Counts | `passed` / `failed` | "3 pass / 0 fail" |
| Dev-host flag | `reason` contains "dev host" | tiny "dev host - provisional" tag, never hidden |
| Timestamp | `tested_utc` | small, muted |

NO raw evidence dumps on the card; evidence lives behind "Details".

### Actions (what the card offers)
1. **View report** -> renderer expands a second floating card with the full
   `report(app_id)` Markdown (scrollable, dismisses after reading).
2. **Details** -> shows the per-test evidence list (`evidence` from
   verdict()), compact rows: name / kind / result / duration.
3. **Dismiss** -> card fades; also auto-dismisses after ~12 seconds of no
   interaction (WARN cards persist until dismissed or acknowledged, because
   a provisional verdict is a decision father must see).

### Visual rules (per the avatar-first law)
- Dark + gold identity; PASS accent gold, FAIL accent red, WARN accent amber.
- Animation: soft bloom/fade beside the avatar, never jarring, never
  full-screen, never a panel.
- No persistent lab icon, button, or status bar. When there is no fresh
  verdict, the lab shows NOTHING.
- The whisper-thin summon affordance (menu glyph) may include a "Laboratory"
  entry that re-opens the latest verdict card on demand.

## Data the renderer consumes (read-only)
- `verdict(app_id)` -> card slots above (plain dicts).
- `report(app_id)` -> Markdown string for the expanded report card.
- Nothing else: the renderer never writes to lab_state.db.
