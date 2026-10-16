# 369-World Bridge — GENESIS's own cloud home

The bridge is the 369 world's independent always-on infrastructure.
The Windows GENESIS connects to it directly — never to the assistant.

## What it is

- `server.py` — stdlib-only HTTP service (no dependencies, no cost)
- `render.yaml` — one-click Render blueprint (free tier, **no card**)

Endpoints: `GET /health`, `POST /v1/heartbeat`, `POST /v1/push`,
`GET /v1/pull`. Bearer-token auth (`BRIDGE_SECRET`).

## YZ's 2-minute signup (his step, when he taps Render)

1. Go to **render.com**, sign up with email or GitHub (no card asked).
2. **New → Blueprint**, point at `369369yz-collab/genesis-windows`.
3. In the dashboard, set env var `BRIDGE_SECRET` to a long random string
   (only he holds it).
4. Deploy → copy the public URL, e.g.
   `https://bridge-369.onrender.com`.
5. In the GENESIS app (settings → bridge), paste the URL + secret once.
   From then: heartbeat every 5 min, memory snapshots sync, she is
   reachable through her own home — independent and always-on.

## Honesty notes

- Render free tier sleeps after 15 min idle; the 5-min heartbeat keeps it
  warm (allowed on the free tier).
- Free disk is ephemeral: the bridge is a relay/cache, NOT the system of
  record. GENESIS holds living memory locally and re-pushes after restarts.
- Without `BRIDGE_SECRET` the server refuses to start (never runs open).
