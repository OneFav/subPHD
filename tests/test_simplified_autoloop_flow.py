from __future__ import annotations

import unittest

from scripts import research_autoloop


class SimplifiedAutoloopFlowTests(unittest.TestCase):
    def test_advance_run_state_after_synced_retries_runner_until_cap_then_reader(self) -> None:
        # New behavior: runner_iteration is incremented BEFORE the cap check.
        # runner_iteration=0 + 1 = 1, 1 >= 2? No → runner.
        # Then runner_iteration=1 + 1 = 2, 2 >= 2? Yes → reader.
        state = {
            "phase": "watch",
            "runner_iteration": 0,
            "runner_iteration_cap": 2,
            "repair_count": 0,
            "last_result_summary": "",
            "remote_status": "running",
            "next_action": "watch",
        }
        snapshot = {
            "watch_status": "synced",
            "local_evidence_paths": {"remote.json": "/tmp/remote.json"},
        }
        next_state = research_autoloop.advance_run_state_after_watch(state, snapshot)
        self.assertEqual(next_state["phase"], "runner")
        self.assertEqual(next_state["remote_status"], "synced")
        self.assertIn("remote.json", next_state["last_result_summary"])

        # runner_iteration is now 1 after first call; second call increments to 2, which hits cap
        state["runner_iteration"] = 1
        capped_state = research_autoloop.advance_run_state_after_watch(state, snapshot)
        self.assertEqual(capped_state["phase"], "reader")
        self.assertEqual(capped_state["next_action"], "reader")
        self.assertEqual(capped_state["runner_done_reason"], "cap_exhausted")

    def test_advance_run_state_after_failed_watch_prefers_self_repair(self) -> None:
        state = {
            "phase": "watch",
            "runner_iteration": 1,
            "runner_iteration_cap": 3,
            "repair_count": 0,
            "last_result_summary": "",
            "remote_status": "running",
            "next_action": "watch",
        }
        snapshot = {
            "watch_status": "failed",
            "failure_reason": "timeout",
            "local_evidence_paths": None,
        }
        next_state = research_autoloop.advance_run_state_after_watch(state, snapshot)
        self.assertEqual(next_state["phase"], "runner")
        self.assertEqual(next_state["repair_count"], 1)
        self.assertEqual(next_state["last_error"], "timeout")
        self.assertEqual(next_state["next_action"], "self_repair_and_retry")

    def test_advance_run_state_after_watch_synced_stays_runner_when_cap_not_exhausted(self):
        state = {
            "phase": "watch", "next_action": "watch",
            "runner_iteration": 1, "runner_iteration_cap": 4,
            "repair_count": 0,
        }
        snapshot = {"watch_status": "synced", "local_evidence_paths": {"result.json": "path"}}
        result = research_autoloop.advance_run_state_after_watch(state, snapshot)
        self.assertEqual(result["phase"], "runner")
        self.assertEqual(result["next_action"], "runner")

    def test_advance_run_state_after_watch_synced_cap_exhausted_goes_reader(self):
        state = {
            "phase": "watch", "next_action": "watch",
            "runner_iteration": 3, "runner_iteration_cap": 4,
            "repair_count": 0,
        }
        snapshot = {"watch_status": "synced", "local_evidence_paths": {"result.json": "path"}}
        result = research_autoloop.advance_run_state_after_watch(state, snapshot)
        self.assertEqual(result["phase"], "reader")
        self.assertEqual(result["runner_done_reason"], "cap_exhausted")

    def test_advance_run_state_after_watch_failed_increments_repair_and_stays_runner(self):
        state = {
            "phase": "watch", "next_action": "watch",
            "runner_iteration": 1, "runner_iteration_cap": 4,
            "repair_count": 0,
        }
        snapshot = {"watch_status": "failed", "failure_reason": "OOM"}
        result = research_autoloop.advance_run_state_after_watch(state, snapshot)
        self.assertEqual(result["phase"], "runner")
        self.assertEqual(result["next_action"], "self_repair_and_retry")
        self.assertEqual(result["repair_count"], 1)

    def test_advance_run_state_after_watch_failed_over_repair_cap_goes_reader(self):
        state = {
            "phase": "watch", "next_action": "watch",
            "runner_iteration": 1, "runner_iteration_cap": 4,
            "repair_count": 2,
        }
        snapshot = {"watch_status": "failed", "failure_reason": "OOM"}
        result = research_autoloop.advance_run_state_after_watch(state, snapshot, repair_cap=3)
        self.assertEqual(result["phase"], "reader")
        self.assertEqual(result["runner_done_reason"], "repair_cap_exhausted")


if __name__ == "__main__":
    unittest.main()
