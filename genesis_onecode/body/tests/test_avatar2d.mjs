/**
 * test_avatar2d.mjs — node tests for body/avatar2d/avatar2d.js
 * Zero dependencies (node:assert/strict only). Run: node test_avatar2d.mjs
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { copyFileSync, appendFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Avatar2D, AVATAR_STATES } from "../avatar2d/avatar2d.js";

const REAL_RIG = "/home/hatch/workspace/genesis_avatar_reverse/rig/genesis.inp";
const BASE_CONFIG = {
  rig_path: REAL_RIG,
  poll_interval_ms: 5000,
  log_level: "info",
  lipsync: { engine: "rhubarb", mouth_param: "ParamMouthOpenY", mouth_param_uuid: 24, status: "staged", talk_animation: "talk" },
};

test("rig-absent: load() returns RIG-ABSENT, runtime stays up, no throw", () => {
  const av = new Avatar2D({ ...BASE_CONFIG, rig_path: "/nonexistent/genesis.inp" });
  const res = av.load();
  assert.equal(res.ok, false);
  assert.equal(res.reason, "RIG-ABSENT");
  assert.equal(av.status().mode, "headless");
  // state machine still works in headless mode
  const s = av.setState("listening");
  assert.equal(s.ok, true);
  assert.equal(av.getState().state, "listening");
  // unknown state rejected, never crashes
  const bad = av.setState("dancing");
  assert.equal(bad.ok, false);
  assert.equal(av.getState().state, "listening");
  // clear log line for the absent rig
  assert.ok(av.logLines.some((l) => l.includes("RIG-ABSENT")),
    "expected a RIG-ABSENT log line");
});

test("rig-present (read-only): header parses, grounded counts hold", () => {
  const av = new Avatar2D(BASE_CONFIG);
  const res = av.load();
  assert.equal(res.ok, true);
  assert.equal(res.mode, "live");
  assert.equal(res.animations, 19);
  assert.equal(res.params, 27);
  assert.equal(res.nodes, 30);
  const st = av.status();
  assert.equal(st.rigName, "genesis");
  assert.equal(st.rigVersion, "1.0-alpha");
  assert.ok(st.snapshot && st.snapshot.sha256.length > 16);
  // all six states transition cleanly
  for (const s of AVATAR_STATES) {
    const r = av.setState(s);
    assert.equal(r.ok, true, `state ${s} rejected`);
    // every mapped animation exists in the rig
    for (const a of r.animations) {
      assert.ok(av.animations.includes(a), `state ${s} maps to unknown animation ${a}`);
    }
  }
});

test("rig-stale: changed file re-parses cleanly, corrupt file keeps cache", () => {
  const dir = mkdtempSync(join(tmpdir(), "av2d-"));
  const copy = join(dir, "genesis.inp");
  copyFileSync(REAL_RIG, copy);
  const av = new Avatar2D({ ...BASE_CONFIG, rig_path: copy });
  assert.equal(av.load().ok, true);
  // simulate the fix pass appending bytes -> re-parse must succeed
  appendFileSync(copy, Buffer.from([0x00, 0x00]));
  const chk = av.checkStale();
  assert.equal(chk.changed, true);
  assert.equal(chk.action, "reloaded");
  assert.equal(av.status().mode, "live");
  // simulate a mid-write corrupt header -> keep cached, stay up
  writeFileSync(copy, Buffer.from("TRNSRTS\0GARBAGE-NOT-JSON{{{"));
  const chk2 = av.checkStale();
  assert.equal(chk2.changed, true);
  assert.ok(["kept-cached", "headless"].includes(chk2.action));
  assert.ok(av.logLines.some((l) => l.includes("RIG-STALE")));
  // runtime still answers
  assert.equal(av.setState("celebrating").ok, true);
});

test("lip-sync hook: staged, feeds mouth values, throwing hook cannot crash", () => {
  const av = new Avatar2D(BASE_CONFIG);
  av.load();
  const seen = [];
  av.registerLipSyncHook({ onMouthOpen: (v) => seen.push(v) });
  const r = av.feedMouthOpen(0.5);
  assert.equal(r.open, 0.5);
  assert.equal(r.talkActive, true);
  assert.equal(r.param, "ParamMouthOpenY");
  assert.deepEqual(seen, [0.5]);
  assert.equal(av.getMouthState().paramUuid, 24);
  // clamping
  assert.equal(av.feedMouthOpen(9).open, 1);
  assert.equal(av.feedMouthOpen(-3).open, 0);
  // a throwing hook is swallowed, runtime stays up
  av.registerLipSyncHook({ onMouthOpen: () => { throw new Error("boom"); } });
  assert.equal(av.feedMouthOpen(0.3).open, 0.3);
  assert.equal(av.setState("idle").ok, true);
});
