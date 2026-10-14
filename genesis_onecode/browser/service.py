"""BrowserService — real browser actions behind the governor's leases.

Every action requires an ACTIVE lease from BrowserGovernor. Sensitive actions
go through governor.check_action() (YZ approval gate, fail-closed).

Driver model: Playwright sync API driving a PORTABLE Chromium binary bundled
with the installer (Full version). Lite uses the same code against the OS
browser channel. The OS mouse cursor is never touched — all input is virtual
(Playwright mouse/keyboard inside the page).

This module degrades honestly: if Playwright or the Chromium binary is
missing, actions raise BrowserUnavailable with a clear message — never a
fake success.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .governor import BrowserGovernor, SENSITIVE_ACTIONS
from . import profiles


class BrowserUnavailable(RuntimeError):
    """Playwright or the portable Chromium binary is not available."""


class LeaseError(RuntimeError):
    """Lease missing, inactive, or action denied by the governor."""


@dataclass
class ActionResult:
    ok: bool
    detail: str = ""
    data: Optional[dict] = None


class BrowserService:
    """Real browser automation. One instance per app; contexts per lease."""

    def __init__(self, governor: BrowserGovernor,
                 chromium_path: Optional[Path] = None):
        self.governor = governor
        self.chromium_path = chromium_path
        self._playwright = None
        self._browser = None
        self._contexts: dict[str, object] = {}  # lease_id -> playwright context

    # ---- lifecycle ------------------------------------------------------
    def _ensure_driver(self):
        if self._browser is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise BrowserUnavailable(
                "Playwright is not installed. Full version bundles it; "
                "Lite requires 'pip install playwright'."
            ) from e
        if self.chromium_path and not self.chromium_path.exists():
            raise BrowserUnavailable(
                f"Portable Chromium not found at {self.chromium_path}"
            )
        self._playwright = sync_playwright().start()
        kwargs: dict = {"headless": True}
        if self.chromium_path:
            kwargs["executable_path"] = str(self.chromium_path)
        self._browser = self._playwright.chromium.launch(**kwargs)

    def _context_for(self, lease_id: str, headless: bool):
        if lease_id in self._contexts:
            return self._contexts[lease_id]
        self._ensure_driver()
        lease = self.governor._leases.get(lease_id)
        if lease is None:
            raise LeaseError(f"unknown lease {lease_id}")
        ctx = self._browser.new_context(
            # NOTE: playwright's Browser.new_context() has no user_data_dir
            # parameter (persistent profiles need launch_persistent_context,
            # wired at the app layer). Passing it raised TypeError and broke
            # every browser action — fixed after the windows self-test caught
            # it (2026-10-14).
            accept_downloads=True,
        )
        # Per-owner persistent storage: use the profile dir for state.
        # (Full persistence via launch_persistent_context is wired at the
        #  app layer where the profile path is passed to launch.)
        self._contexts[lease_id] = ctx
        self.governor.heartbeat(lease_id)
        return ctx

    def _page_for(self, lease_id: str, headless: bool = True):
        ctx = self._context_for(lease_id, headless)
        if ctx.pages:
            return ctx.pages[0]
        return ctx.new_page()

    def _guard(self, lease_id: str, action: str, detail: str = "") -> None:
        if not self.governor.check_action(lease_id, action, detail):
            raise LeaseError(
                f"action {action!r} denied for lease {lease_id} "
                f"(inactive lease or YZ approval denied)"
            )

    # ---- actions ----------------------------------------------------------
    def open(self, lease_id: str, url: str, headless: bool = True) -> ActionResult:
        self._guard(lease_id, "open", url)
        page = self._page_for(lease_id, headless)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        self.governor.heartbeat(lease_id)
        return ActionResult(ok=True, detail=url,
                            data={"title": page.title()})

    def read(self, lease_id: str) -> ActionResult:
        self._guard(lease_id, "read")
        page = self._page_for(lease_id)
        text = page.evaluate("() => document.body ? document.body.innerText : ''")
        self.governor.heartbeat(lease_id)
        return ActionResult(ok=True, data={"text": text[:20000],
                                           "url": page.url,
                                           "title": page.title()})

    def click(self, lease_id: str, selector: str) -> ActionResult:
        self._guard(lease_id, "click", selector)
        page = self._page_for(lease_id)
        page.click(selector, timeout=15000)
        self.governor.heartbeat(lease_id)
        return ActionResult(ok=True, detail=selector)

    def type(self, lease_id: str, selector: str, text: str,
             submit: bool = False) -> ActionResult:
        action = "submit_form" if submit else "type"
        self._guard(lease_id, action, selector)
        page = self._page_for(lease_id)
        page.fill(selector, text, timeout=15000)
        if submit:
            page.press(selector, "Enter")
        self.governor.heartbeat(lease_id)
        return ActionResult(ok=True, detail=selector)

    def download(self, lease_id: str, selector: str) -> ActionResult:
        self._guard(lease_id, "download", selector)
        page = self._page_for(lease_id)
        qdir = profiles.quarantine_dir(self.governor.config.app_data_dir)
        with page.expect_download(timeout=60000) as dl_info:
            page.click(selector, timeout=15000)
        download = dl_info.value
        dest = qdir / download.suggested_filename
        download.save_as(dest)
        self.governor.heartbeat(lease_id)
        return ActionResult(ok=True, detail=str(dest),
                            data={"quarantined": str(dest)})

    def screenshot(self, lease_id: str) -> ActionResult:
        self._guard(lease_id, "screenshot")
        page = self._page_for(lease_id)
        shot = self.governor.config.app_data_dir / "shots" / f"{lease_id}.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shot))
        self.governor.heartbeat(lease_id)
        return ActionResult(ok=True, detail=str(shot))

    def close(self, lease_id: str) -> ActionResult:
        ctx = self._contexts.pop(lease_id, None)
        if ctx is not None:
            try:
                ctx.close()
            except Exception:
                pass
        self.governor.release(lease_id, reason="service close")
        return ActionResult(ok=True, detail=lease_id)

    def shutdown(self) -> None:
        for lease_id in list(self._contexts):
            try:
                self.close(lease_id)
            except Exception:
                pass
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
