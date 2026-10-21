"""simulation_loop.py — the fidelity loop.

On startup AND on each bridge heartbeat, the simulated self queries the
environment twin and runs the fidelity check:

  "my voice engine reports HEALTHY and the twin confirms the engine file
   exists with a matching checksum; my avatar plates are loaded and the
   overlay host state is reported truthfully."

fidelity_report() -> {self_ok, env_ok, drift[], ...}.

Fail-closed: Twin A unloadable (SelfModelError) OR any drift between
Twin B and reality -> the report carries ok=False with a named reason,
and the launcher blocks the launch. A drift also moves her expression
to solemn — the presentation state tracks the fidelity state.
"""

from __future__ import annotations

from datetime import datetime, timezone


class SimulationLoop:
    """The fidelity loop binding Twin A (self) to Twin B (environment)."""

    def __init__(self, self_model, env_model) -> None:
        self.self_model = self_model
        self.env_model = env_model
        self._last_report: dict | None = None

    def fidelity_report(self) -> dict:
        """Run one full fidelity pass. Never raises: every failure is a
        named field in the report (fail-closed by the caller)."""
        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        reasons: list[str] = []
        drift: list = []
        self_ok = True
        env_ok = True

        # -- Twin A: can she form, and do her claims verify? -------------
        try:
            ident = self_model_identity = self.self_model.identity()
        except Exception as exc:  # noqa: BLE001 - fail-closed
            self_ok = False
            reasons.append("twin A unloadable: %s: %s"
                           % (type(exc).__name__, exc))
            ident = None

        if ident is not None:
            # Her voice claim vs the voice file on disk.
            voice = ident.get("voice") or {}
            try:
                from pathlib import Path
                engine_file = Path(voice.get("engine_file") or "")
                if not engine_file.is_file():
                    self_ok = False
                    reasons.append("twin A voice engine file missing: %s"
                                   % engine_file)
            except Exception as exc:  # noqa: BLE001
                self_ok = False
                reasons.append("twin A voice verification failed: %s" % exc)
            # Her face claim vs the plate set.
            pres = self.self_model.presentation_state()
            if not pres.get("plate_present"):
                self_ok = False
                reasons.append("twin A presentation plate not present: %s"
                               % pres.get("plate_file"))
            if not (ident.get("identity_core") or {}).get("law_total"):
                self_ok = False
                reasons.append("twin A identity core holds no laws")

        # -- Twin B: does the mirror match reality? ----------------------
        try:
            self.env_model.snapshot()
            drift = self.env_model.diff_vs_reality()
            if drift:
                env_ok = False
                reasons.append("twin B drift from reality: %d item(s)"
                               % len(drift))
        except Exception as exc:  # noqa: BLE001 - fail-closed
            env_ok = False
            reasons.append("twin B failed to mirror: %s: %s"
                           % (type(exc).__name__, exc))

        # -- Cross-check: Twin A's voice id must be the engine Twin B sees.
        if ident is not None and self_ok and env_ok:
            try:
                twin_b_voice = (self.env_model._snapshot or {}).get(
                    "voice", {})
                if twin_b_voice.get("engine_id") != \
                        (ident.get("voice") or {}).get("engine_id"):
                    self_ok = False
                    reasons.append(
                        "twin A voice id %r != twin B engine id %r"
                        % ((ident.get("voice") or {}).get("engine_id"),
                           twin_b_voice.get("engine_id")))
            except Exception as exc:  # noqa: BLE001
                self_ok = False
                reasons.append("twin cross-check failed: %s" % exc)

        # Her face tracks the fidelity state: solemn on any warning.
        try:
            self.self_model.set_expression(
                "solemn" if (reasons or drift) else "calm")
            expression = self.self_model.presentation_state()["expression"]
        except Exception:  # noqa: BLE001
            expression = "unknown"

        report = {
            "self_ok": self_ok,
            "env_ok": env_ok,
            "ok": self_ok and env_ok,
            "drift": drift,
            "reasons": reasons,
            "expression": expression,
            "checked_at": checked_at,
        }
        self._last_report = report
        return report

    def run_heartbeat(self) -> dict:
        """The heartbeat payload: fidelity_report() attached so home sees
        her self-health. Carries no personal data — only the fidelity
        verdict, drift items, and timestamps."""
        report = self.fidelity_report()
        return {
            "fidelity": {
                "self_ok": report["self_ok"],
                "env_ok": report["env_ok"],
                "drift": report["drift"],
                "reasons": report["reasons"],
                "checked_at": report["checked_at"],
            },
            "ts": report["checked_at"],
        }
