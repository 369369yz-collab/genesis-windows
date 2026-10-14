"""Tests for the browser governor (no real browser needed)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from browser.governor import (
    BrowserGovernor, GovernorConfig, SessionState, SENSITIVE_ACTIONS,
)
from browser import profiles


class GovernorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.gov = BrowserGovernor(GovernorConfig(
            max_concurrent=2, app_data_dir=self.tmp))

    def test_acquire_within_cap_is_active(self):
        l1 = self.gov.acquire("genesis", "test one")
        l2 = self.gov.acquire("agent-1", "test two")
        self.assertEqual(l1.state, SessionState.ACTIVE)
        self.assertEqual(l2.state, SessionState.ACTIVE)

    def test_overflow_queues(self):
        self.gov.acquire("genesis", "one")
        self.gov.acquire("agent-1", "two")
        l3 = self.gov.acquire("agent-2", "three")
        self.assertEqual(l3.state, SessionState.QUEUED)
        st = self.gov.status()
        self.assertEqual(st["active"], 2)
        self.assertEqual(st["queued"], 1)

    def test_release_promotes_queued(self):
        l1 = self.gov.acquire("genesis", "one")
        self.gov.acquire("agent-1", "two")
        l3 = self.gov.acquire("agent-2", "three")
        self.gov.release(l1.lease_id)
        self.assertEqual(
            self.gov._leases[l3.lease_id].state, SessionState.ACTIVE)

    def test_owner_required(self):
        with self.assertRaises(ValueError):
            self.gov.acquire("", "no owner")
        with self.assertRaises(ValueError):
            self.gov.acquire("genesis", "")

    def test_non_sensitive_action_allowed(self):
        l1 = self.gov.acquire("genesis", "browse")
        self.assertTrue(self.gov.check_action(l1.lease_id, "open", "http://x"))

    def test_sensitive_action_denied_without_callback(self):
        l1 = self.gov.acquire("genesis", "shop")
        # fail-closed: no approval callback => denied
        self.assertFalse(self.gov.check_action(l1.lease_id, "purchase", "item"))
        self.assertIn("purchase", SENSITIVE_ACTIONS)

    def test_sensitive_action_with_approving_callback(self):
        gov = BrowserGovernor(GovernorConfig(
            max_concurrent=2, app_data_dir=self.tmp,
            approval_callback=lambda lease, action, detail: True))
        l1 = gov.acquire("genesis", "shop")
        self.assertTrue(gov.check_action(l1.lease_id, "purchase", "item"))

    def test_reap_kills_expired(self):
        gov = BrowserGovernor(GovernorConfig(
            max_concurrent=2, app_data_dir=self.tmp,
            default_ttl_seconds=0.01, heartbeat_timeout_seconds=3600))
        l1 = gov.acquire("genesis", "short")
        import time
        time.sleep(0.05)
        killed = gov.reap()
        self.assertIn(l1.lease_id, killed)

    def test_profiles_isolated_per_owner(self):
        d1 = profiles.profile_dir(self.tmp, "genesis")
        d2 = profiles.profile_dir(self.tmp, "agent-1")
        self.assertNotEqual(d1, d2)
        self.assertTrue(d1.is_dir() and d2.is_dir())
        with self.assertRaises(ValueError):
            profiles.profile_dir(self.tmp, "../evil")

    def test_quarantine_dir_created(self):
        q = profiles.quarantine_dir(self.tmp)
        self.assertTrue(q.is_dir())

    def test_ledger_written(self):
        l1 = self.gov.acquire("genesis", "audit me")
        self.gov.release(l1.lease_id)
        ledger = self.tmp / "browser_ledger.jsonl"
        self.assertTrue(ledger.exists())
        content = ledger.read_text(encoding="utf-8")
        self.assertIn("acquire", content)
        self.assertIn("release", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
