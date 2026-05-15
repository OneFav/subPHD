from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import research_loop_contract as contract


class SimplifiedAutoresearchContractTests(unittest.TestCase):
    def write_config(self, root: Path) -> None:
        (root / "research_agent.toml").write_text(
            """
default_hours = 10
default_max_runs = 30
default_poll_seconds = 300

[remote]
ssh_key = "key"
host = "host"
port = 22
remote_code_dir = "/remote/code"
remote_result_dir = "/remote/results"

[artifacts]
person_program = "person_program.md"
agent_program = "agent_program.md"
loop_state = ".omx/state/research_loop_state.json"
assignment = ".omx/state/research_assignment.json"
watch_snapshot = ".omx/state/research_watch_snapshot.json"
watch_events = ".omx/state/research_watch_events.jsonl"
""".strip(),
            encoding="utf-8",
        )

    def seed_program_files(self, root: Path) -> None:
        (root / "person_program.md").write_text(
            "# person_program.md\n\n## 1. Core Objective for This Cycle\nBuild the strongest paper evidence package.\n\n## 2. Default Priority Order\nFirst mainline evidence.\n\n## 3. Reader Responsibilities\nThe reader defines the next step.\n\nThis paper direction needs the best evidence package.\n",
            encoding="utf-8",
        )

    def test_bootstrap_creates_run_state_with_isolated_context_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(root)
            self.seed_program_files(root)
            config = {"artifacts": {}}
            paths = contract.bootstrap_state_artifacts(root, config)
            self.assertTrue(hasattr(paths, "task_state"))
            state = contract.load_task_state(paths.task_state)
            self.assertEqual(state["phase"], "reader")
            self.assertEqual(state["window_role"], "reader")
            self.assertIn("next_action", state)

    def test_resolve_execution_backend_defaults_to_ssh_when_remote_config_exists(self) -> None:
        config = {"remote": {"host": "host", "ssh_key": "key", "remote_code_dir": "/code"}}
        self.assertEqual(contract.resolve_execution_backend(config), "ssh")

    def test_resolve_execution_backend_uses_explicit_local(self) -> None:
        config = {"execution": {"backend": "local"}, "remote": {"host": "host"}}
        self.assertEqual(contract.resolve_execution_backend(config), "local")

    def test_resolve_execution_backend_rejects_unknown_backend(self) -> None:
        with self.assertRaises(ValueError):
            contract.resolve_execution_backend({"execution": {"backend": "docker"}})

    def test_append_ai_worklog_entry_writes_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / ".omx" / "logs" / "ai-worklog.md"
            contract.append_ai_worklog_entry(
                log_path,
                {
                    "role": "runner",
                    "start_time": "2026-04-13T00:00:00Z",
                    "current_objective": "test objective",
                    "runner_iteration": 1,
                    "runner_iteration_cap": 3,
                    "reader_iteration": 2,
                    "reader_iteration_cap": 5,
                    "success_condition": "metric > 0.5",
                    "remote_status": "running",
                    "latest_result_summary": "none yet",
                    "next_action": "watch remote",
                },
            )
            text = log_path.read_text(encoding="utf-8")
            self.assertIn("runner", text)
            self.assertIn("test objective", text)
            self.assertIn("metric > 0.5", text)
            self.assertIn("watch remote", text)

    def test_read_json_accepts_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "watch.json"
            path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"ok": True}).encode("utf-8"))
            self.assertEqual(contract.read_json(path), {"ok": True})

    def test_rendered_prompt_hash_matches_canonical_hash_when_no_pending_prompt(self) -> None:
        run_state = contract.default_task_state({})
        canonical = contract.compute_prompt_contract_hash("person", "agent", "reader", run_state)
        rendered = contract.compute_prompt_contract_hash("person", "agent", "reader", run_state)
        self.assertEqual(canonical, rendered)

    def test_default_task_state_has_sprint_contract_field(self):
        state = contract.default_task_state({})
        self.assertIsNone(state.get("sprint_contract"))
        self.assertIsNone(state.get("runner_done_reason"))
        self.assertEqual(state.get("no_improvement_count"), 0)
        self.assertEqual(state["runner_iteration_cap"], 4)

    def test_default_task_state_runner_cap_from_config(self):
        config = {"loop": {"runner_turn_cap": 7}}
        state = contract.default_task_state(config)
        self.assertEqual(state["runner_iteration_cap"], 7)

    def test_validate_task_state_allows_done_phase(self):
        state = contract.default_task_state({})
        state["phase"] = "done"
        validated = contract.validate_task_state(state)
        self.assertEqual(validated["phase"], "done")

    def test_validate_task_state_allows_abandoned_phase(self):
        state = contract.default_task_state({})
        state["phase"] = "abandoned"
        validated = contract.validate_task_state(state)
        self.assertEqual(validated["phase"], "abandoned")

    def test_validate_task_state_allows_needs_human_phase(self):
        state = contract.default_task_state({})
        state["phase"] = "needs_human"
        validated = contract.validate_task_state(state)
        self.assertEqual(validated["phase"], "needs_human")

    def test_validate_task_state_allows_structured_success_condition(self):
        state = contract.default_task_state({})
        state["sprint_contract"] = {
            "sprint_id": "s1",
            "research_question": "test",
            "success_condition": {"mode": "all", "conditions": [{"metric": "acc", "op": ">=", "threshold": 0.9}]}
        }
        validated = contract.validate_task_state(state)
        self.assertEqual(validated["sprint_contract"]["success_condition"]["mode"], "all")

    def test_evaluate_success_condition_all_mode_both_pass(self):
        sc = {"mode": "all", "conditions": [
            {"metric": "acc", "op": ">=", "threshold": 0.8},
            {"metric": "loss", "op": "<", "threshold": 0.5},
        ]}
        task_state = {"sprint_contract": {"metrics": {"acc": 0.9, "loss": 0.3}}}
        satisfied, details = contract.evaluate_success_condition(sc, task_state)
        self.assertTrue(satisfied)

    def test_evaluate_success_condition_all_mode_one_fails(self):
        sc = {"mode": "all", "conditions": [
            {"metric": "acc", "op": ">=", "threshold": 0.8},
            {"metric": "loss", "op": "<", "threshold": 0.1},
        ]}
        task_state = {"sprint_contract": {"metrics": {"acc": 0.9, "loss": 0.3}}}
        satisfied, details = contract.evaluate_success_condition(sc, task_state)
        self.assertFalse(satisfied)

    def test_evaluate_success_condition_any_mode(self):
        sc = {"mode": "any", "conditions": [
            {"metric": "acc", "op": ">=", "threshold": 0.99},
            {"metric": "loss", "op": "<", "threshold": 0.5},
        ]}
        task_state = {"sprint_contract": {"metrics": {"acc": 0.9, "loss": 0.3}}}
        satisfied, details = contract.evaluate_success_condition(sc, task_state)
        self.assertTrue(satisfied)

    def test_evaluate_success_condition_legacy_string_returns_false(self):
        satisfied, details = contract.evaluate_success_condition("manual check needed", {})
        self.assertFalse(satisfied)
        self.assertIn("legacy_string", details)

    def test_compute_resume_key_ignores_volatile_fields(self):
        key1 = contract.compute_resume_key("runner", {}, "abc123", False)
        key2 = contract.compute_resume_key("runner", {"metrics": {"acc": 0.99}, "last_result_summary": "changed a lot", "updated_at": "2025-01-01T00:00:00Z"}, "abc123", False)
        self.assertEqual(key1, key2)

    def test_compute_resume_key_changes_on_new_human_prompt(self):
        key1 = contract.compute_resume_key("runner", {}, "abc123", False)
        key2 = contract.compute_resume_key("runner", {}, "abc123", True)
        self.assertNotEqual(key1, key2)


if __name__ == "__main__":
    unittest.main()
