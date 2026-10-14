/**
 * avatar2d.js — 2D avatar runtime SKELETON for the GENESIS ONE-CODE body.
 *
 * Consumes the finished 2D rig at the path given in config.json. The rig file
 * format was verified read-only on 2026-10-14 (phase-1 file, fix pass running
 * on it owned by another specialist — this runtime NEVER writes to the rig):
 *
 *   magic      : 8 bytes  "TRNSRTS\0"
 *   header     : JSON object starting at byte 12, brace-matched to its end
 *   header keys: meta, physics, nodes, param, automation, animations
 *   observed   : meta.name="genesis", meta.version="1.0-alpha",
 *                physics={pixelsPerMeter:1000.0, gravity:9.8},
 *                30 nodes (Root -> body, physics_anchor_ParamAngleX_ParamAngleZ,
 *                physics_anchor_ParamAngleY), 27 params (uuid 20..46),
 *                19 animations (idle, smile, surprise, sad, angry, shy,
 *                head_yaw, head_pitch, head_roll, head_shake, body_sway,
 *                body_bow, talk, smirk, cheek, blink, brows, brow_form, sweep)
 *
 * The fix pass may change counts/names after load; the loader validates
 * structurally (magic + JSON + required keys) and never hard-requires the
 * phase-1 numbers. Graceful degradation contract:
 *   RIG-ABSENT -> placeholder mode, clear log, no throw, every method safe.
 *   RIG-STALE  -> rig file changed after load (fix pass still running):
 *                 re-parse; success -> adopt new header; failure -> keep the
 *                 cached header and stay up. Never crashes.
 *
 * Lip-sync: staged hook point for Rhubarb (vendored, parked per YZ order).
 * Mouth openness 0..1 drives ParamMouthOpenY (uuid 24) + the "talk" animation.
 *
 * Technical English. Zero spend. Part of the GENESIS ONE-CODE tree.
 */

import { readFileSync, statSync } from "node:fs";
import { createHash } from "node:crypto";

/** The six avatar states ordered by YZ (formula override row 1). */
export const AVATAR_STATES = Object.freeze([
  "idle",
  "listening",
  "thinking",
  "working",
  "making_something",
  "celebrating",
]);

/**
 * State -> rig animation mapping. Every animation name below was verified to
 * exist in the phase-1 rig header on 2026-10-14. If the fix pass renames or
 * removes one, the loader prunes the map and logs it instead of crashing.
 */
const STATE_ANIMATION_MAP = Object.freeze({
  idle: ["idle", "blink", "body_sway"],
  listening: ["idle", "blink", "head_pitch"],
  thinking: ["brows", "head_roll", "idle"],
  working: ["idle", "blink", "body_sway", "sweep"],
  making_something: ["smile", "head_yaw", "body_sway", "idle"],
  celebrating: ["smile", "smirk", "body_bow", "surprise"],
});

const RIG_MAGIC = Buffer.from("TRNSRTS\0", "latin1");

function log(level, ...args) {
  const line = `[avatar2d:${level}] ${args.join(" ")}`;
  // eslint-disable-next-line no-console
  console.log(line);
  return line;
}

/** Extract the JSON header: magic check + brace-matched object from byte 12. */
function parseRigHeader(buf) {
  if (buf.length < 16 || !buf.subarray(0, 8).equals(RIG_MAGIC)) {
    throw new Error("bad magic: not a TRNSRTS rig file");
  }
  const start = buf.indexOf(0x7b, 8); // first '{'
  if (start < 0) throw new Error("no JSON header found after magic");
  let depth = 0;
  let inStr = false;
  let esc = false;
  for (let i = start; i < buf.length; i++) {
    const c = buf[i];
    if (inStr) {
      if (esc) esc = false;
      else if (c === 0x5c) esc = true;
      else if (c === 0x22) inStr = false;
    } else {
      if (c === 0x22) inStr = true;
      else if (c === 0x7b) depth++;
      else if (c === 0x7d) {
        depth--;
        if (depth === 0) {
          const header = JSON.parse(buf.subarray(start, i + 1).toString("utf8"));
          return { header, headerEnd: i + 1 };
        }
      }
    }
  }
  throw new Error("unterminated JSON header in rig file");
}

function countNodes(node) {
  let n = 1;
  for (const ch of node.children || []) n += countNodes(ch);
  return n;
}

export class Avatar2D {
  /**
   * @param {object} config - { rig_path, poll_interval_ms, log_level, lipsync }
   */
  constructor(config = {}) {
    this.config = config;
    this.rigPath = config.rig_path || null;
    this.state = "idle";
    this.mode = "unloaded"; // unloaded | live | headless(rig-absent) | stale
    this.header = null;
    this.animations = [];
    this.params = [];
    this.nodeCount = 0;
    this.snapshot = null; // { mtimeMs, size, sha256 } taken at last good load
    this.stateMap = { ...STATE_ANIMATION_MAP };
    this.mouth = { open: 0.0, talkActive: false }; // lip-sync hook state
    this.lipsyncHook = null;
    this.logLines = [];
  }

  _log(level, ...args) {
    this.logLines.push(log(level, ...args));
  }

  _snapshot(buf, st) {
    return {
      mtimeMs: st.mtimeMs,
      size: st.size,
      sha256: createHash("sha256").update(buf).digest("hex"),
    };
  }

  /** Load (or reload) the rig. Never throws: returns a result object. */
  load() {
    if (!this.rigPath) {
      this._enterHeadless("RIG-ABSENT", "no rig_path configured");
      return { ok: false, reason: "RIG-ABSENT", detail: "no rig_path configured" };
    }
    let st;
    try {
      st = statSync(this.rigPath);
    } catch (e) {
      // The fix pass has not finished yet, or the path is wrong.
      this._enterHeadless("RIG-ABSENT", `stat failed: ${e.message}`);
      return { ok: false, reason: "RIG-ABSENT", detail: `stat failed: ${e.message}` };
    }
    let buf;
    try {
      buf = readFileSync(this.rigPath);
    } catch (e) {
      this._enterHeadless("RIG-ABSENT", `read failed: ${e.message}`);
      return { ok: false, reason: "RIG-ABSENT", detail: `read failed: ${e.message}` };
    }
    let parsed;
    try {
      parsed = parseRigHeader(buf);
    } catch (e) {
      // Mid-write by the fix pass: keep whatever we had, stay up.
      this.mode = this.header ? "stale" : "headless";
      this._log("warn", `RIG-STALE: header parse failed (${e.message}) — keeping cached state, retry later`);
      return { ok: false, reason: "RIG-STALE", detail: e.message, keptCached: !!this.header };
    }
    const { header } = parsed;
    if (!header.meta || !header.nodes || !header.animations) {
      this.mode = this.header ? "stale" : "headless";
      this._log("warn", "RIG-STALE: header missing required keys (meta/nodes/animations) — keeping cached state");
      return { ok: false, reason: "RIG-STALE", detail: "missing required header keys", keptCached: !!this.header };
    }
    this.header = header;
    this.animations = Object.keys(header.animations || {});
    this.params = Array.isArray(header.param) ? header.param : [];
    this.nodeCount = countNodes(header.nodes);
    this.snapshot = this._snapshot(buf, st);
    this.mode = "live";
    this._pruneStateMap();
    this._log(
      "info",
      `rig loaded: name=${header.meta.name} version=${header.meta.version} ` +
        `nodes=${this.nodeCount} params=${this.params.length} ` +
        `animations=${this.animations.length} sha256=${this.snapshot.sha256.slice(0, 16)}...`
    );
    return { ok: true, mode: "live", animations: this.animations.length, params: this.params.length, nodes: this.nodeCount };
  }

  _enterHeadless(reason, detail) {
    this.mode = "headless";
    this._log("warn", `${reason}: ${detail} — avatar in placeholder mode, runtime stays up`);
  }

  /** Drop state->animation entries whose animation no longer exists in the rig. */
  _pruneStateMap() {
    const have = new Set(this.animations);
    for (const s of Object.keys(this.stateMap)) {
      const before = this.stateMap[s].length;
      this.stateMap[s] = this.stateMap[s].filter((a) => have.has(a));
      if (this.stateMap[s].length !== before) {
        this._log("warn", `RIG-STALE: pruned ${before - this.stateMap[s].length} animation(s) from state '${s}' (fix pass changed the rig)`);
      }
    }
  }

  /**
   * Check whether the rig file changed since the last good load.
   * Never throws. Returns { changed:boolean, action }.
   */
  checkStale() {
    if (this.mode !== "live" || !this.snapshot) return { changed: false, action: "none" };
    let st;
    try {
      st = statSync(this.rigPath);
    } catch {
      this._enterHeadless("RIG-ABSENT", "rig file vanished after load");
      return { changed: true, action: "headless" };
    }
    if (st.mtimeMs === this.snapshot.mtimeMs && st.size === this.snapshot.size) {
      return { changed: false, action: "none" };
    }
    this._log("warn", `RIG-STALE: rig file changed on disk (size ${this.snapshot.size} -> ${st.size}) — attempting re-parse`);
    const res = this.load();
    if (res.ok) {
      this._log("info", "RIG-RELOADED: new rig header adopted cleanly");
      return { changed: true, action: "reloaded" };
    }
    this.mode = "stale";
    this._log("warn", "RIG-STALE: re-parse failed — continuing with cached header, will retry");
    return { changed: true, action: "kept-cached" };
  }

  /** Transition the state machine. Unknown states are rejected, never crash. */
  setState(next) {
    if (!AVATAR_STATES.includes(next)) {
      this._log("warn", `unknown avatar state '${next}' — staying in '${this.state}'`);
      return { ok: false, state: this.state, reason: "unknown-state" };
    }
    const prev = this.state;
    this.state = next;
    const anims = this.stateMap[next] || [];
    this._log("info", `state ${prev} -> ${next} (animations: ${anims.join(",") || "none"})`);
    return { ok: true, prev, state: next, animations: anims };
  }

  getState() {
    return { state: this.state, mode: this.mode, animations: this.stateMap[this.state] || [] };
  }

  /**
   * STAGED lip-sync hook point for Rhubarb.
   * hook = { onMouthOpen?: (v:number)=>void }. feedMouthOpen(v) drives
   * ParamMouthOpenY + the "talk" animation. No-op (logged) until a real
   * Rhubarb backend registers, because voice is PARKED per YZ order.
   */
  registerLipSyncHook(hook) {
    this.lipsyncHook = hook || null;
    this._log("info", `lip-sync hook ${this.lipsyncHook ? "registered (staged)" : "cleared"} — Rhubarb backend not active (voice parked)`);
    return { ok: true, staged: true };
  }

  /** Feed a mouth-openness value 0..1 (from Rhubarb when active). */
  feedMouthOpen(v) {
    const clamped = Math.max(0, Math.min(1, Number(v) || 0));
    this.mouth.open = clamped;
    this.mouth.talkActive = clamped > 0.02;
    if (this.lipsyncHook && typeof this.lipsyncHook.onMouthOpen === "function") {
      try {
        this.lipsyncHook.onMouthOpen(clamped);
      } catch (e) {
        this._log("warn", `lip-sync hook threw (${e.message}) — ignored, runtime stays up`);
      }
    }
    return { open: clamped, talkActive: this.mouth.talkActive, param: "ParamMouthOpenY" };
  }

  getMouthState() {
    return { ...this.mouth, param: "ParamMouthOpenY", paramUuid: 24 };
  }

  /** Summary for the HUD / diagnostics. Never throws. */
  status() {
    return {
      state: this.state,
      mode: this.mode,
      rigPath: this.rigPath,
      rigName: this.header ? this.header.meta.name : null,
      rigVersion: this.header ? this.header.meta.version : null,
      animations: this.animations.length,
      params: this.params.length,
      nodes: this.nodeCount,
      snapshot: this.snapshot ? { ...this.snapshot, sha256: this.snapshot.sha256.slice(0, 16) + "..." } : null,
      lipsync: this.config.lipsync || null,
    };
  }
}

export default Avatar2D;
