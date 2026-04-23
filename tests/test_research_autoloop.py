from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.research_autoloop import advance_run_state_after_watch
from scripts.research_agent_cli import load_project_config
from scripts.research_loop_contract import (
    SCHEMA_VERSION,
    bootstrap_state_artifacts,
    compute_rendered_prompt_contract_hash,
    default_loop_state,
    default_watch_snapshot,
    load_loop_state,
    load_run_state,
    read_json,
)


class ResearchAutoloopTests(unittest.TestCase):
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
watch_snapshot = ".omx/state/research_watch_snapshot.json"
watch_events = ".omx/state/research_watch_events.jsonl"
""".strip(),
            encoding="utf-8",
        )

    def test_missing_person_program_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(root)
            with self.assertRaises(FileNotFoundError):
                bootstrap_state_artifacts(root, {})

    def test_missing_agent_program_bootstraps_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(root)
            (root / "person_program.md").write_text(
                "# person_program.md\n\n## 1. Core Objective for This Cycle\nBuild the strongest paper evidence package.\n\n## 2. Default Priority Order\nFirst mainline evidence.\n\n## 3. Reader Responsibilities\nThe reader defines the next step.\n\nThis paper direction needs the best evidence package.\n",
                encoding="utf-8",
            )
            paths = bootstrap_state_artifacts(root, {})
            self.assertTrue(paths.agent_program.exists())
            self.assertTrue(paths.watch_events.exists())
            lines = paths.watch_events.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["event_type"], "bootstrap_agent_program")

    def test_invalid_schema_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(root)
            (root / "person_program.md").write_text(
                "# person_program.md\n\n## 1. Core Objective for This Cycle\nBuild the strongest paper evidence package.\n\n## 2. Default Priority Order\nFirst mainline evidence.\n\n## 3. Reader Responsibilities\nThe reader defines the next step.\n\nThis paper direction needs the best evidence package.\n",
                encoding="utf-8",
            )
            paths = bootstrap_state_artifacts(root, {})
            bad = default_loop_state({})
            bad["schema_version"] = 999
            paths.loop_state.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_loop_state(paths.loop_state)

    def test_missing_required_loop_state_key_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(root)
            (root / "person_program.md").write_text(
                "# person_program.md\n\n## 1. Core Objective for This Cycle\nBuild the strongest paper evidence package.\n\n## 2. Default Priority Order\nFirst mainline evidence.\n\n## 3. Reader Responsibilities\nThe reader defines the next step.\n\nThis paper direction needs the best evidence package.\n",
                encoding="utf-8",
            )
            paths = bootstrap_state_artifacts(root, {})
            bad = default_loop_state({})
            bad.pop("updated_at")
            paths.loop_state.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_loop_state(paths.loop_state)

    def test_advance_run_state_after_synced_hands_off_by_cap(self) -> None:
        run_state = {
            "phase": "watch",
            "runner_iteration": 1,
            "runner_iteration_cap": 1,
            "repair_count": 0,
            "remote_status": "submitted",
            "last_result_summary": "",
            "next_action": "watch",
        }
        next_state = advance_run_state_after_watch(run_state, {"watch_status": "synced", "local_evidence_paths": {"x.json": "y"}})
        self.assertEqual(next_state["phase"], "reader")
        self.assertEqual(next_state["next_action"], "reader")

    def test_rendered_prompt_hash_uses_same_basis_as_launcher(self) -> None:
        run_state = {
            "phase": "runner",
            "current_objective": "obj",
            "pending_human_prompt": {
                "target": "next_actual_agent",
                "text": "focus on ablation table",
                "created_at": "2026-04-14T00:00:00Z",
            },
        }
        hash_from_autoloop_basis = compute_rendered_prompt_contract_hash("person-a", "agent-a", "runner", run_state)
        hash_from_launcher_basis = compute_rendered_prompt_contract_hash("person-a", "agent-a", "runner", run_state)
        self.assertEqual(hash_from_autoloop_basis, hash_from_launcher_basis)

    def test_role_local_window_policy_uses_resume_same_role_below_budget(self) -> None:
        from scripts import research_autoloop

        loop_state = default_loop_state({})
        loop_state.update({
            "window_role": "runner",
            "role_window_id": "runner-window-1",
            "resume_budget": 3,
            "resume_count": 2,
            "last_prompt_role": "runner",
            "prompt_contract_hash": "abc",
            "big_round_id": "big-round-1",
        })
        policy = research_autoloop.choose_continuation_policy(
            loop_state=loop_state,
            role="runner",
            prompt_contract_hash="abc",
            handoff_status="valid",
        )
        self.assertEqual(policy["resume_mode"], "resume_same_role")
        self.assertEqual(policy["next_resume_count"], 3)

    def test_role_local_window_policy_rolls_over_after_budget_exhaustion(self) -> None:
        from scripts import research_autoloop

        loop_state = default_loop_state({})
        loop_state.update({
            "window_role": "runner",
            "role_window_id": "runner-window-1",
            "resume_budget": 3,
            "resume_count": 3,
            "last_prompt_role": "runner",
            "prompt_contract_hash": "abc",
            "big_round_id": "big-round-1",
        })
        policy = research_autoloop.choose_continuation_policy(
            loop_state=loop_state,
            role="runner",
            prompt_contract_hash="abc",
            handoff_status="valid",
        )
        self.assertEqual(policy["resume_mode"], "fresh")
        self.assertTrue(policy["start_new_window"])

    def test_role_change_starts_fresh_role_local_window(self) -> None:
        from scripts import research_autoloop

        loop_state = default_loop_state({})
        loop_state.update({
            "window_role": "reader",
            "role_window_id": "reader-window-1",
            "resume_budget": 3,
            "resume_count": 1,
            "last_prompt_role": "reader",
            "prompt_contract_hash": "abc",
            "big_round_id": "big-round-1",
        })
        policy = research_autoloop.choose_continuation_policy(
            loop_state=loop_state,
            role="runner",
            prompt_contract_hash="abc",
            handoff_status="valid",
        )
        self.assertEqual(policy["resume_mode"], "fresh")
        self.assertTrue(policy["start_new_window"])
        self.assertEqual(policy["next_window_role"], "runner")

    def test_resolve_authoritative_handoff_marks_invalid_payload(self) -> None:
        from scripts import research_autoloop

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(root)
            (root / "person_program.md").write_text(
                "# person_program.md\n\n## 1. Core Objective for This Cycle\nBuild the strongest paper evidence package.\n\n## 2. Default Priority Order\nFirst mainline evidence.\n\n## 3. Reader Responsibilities\nThe reader defines the next step.\n\nThis paper direction needs the best evidence package.\n",
                encoding="utf-8",
            )
            paths = bootstrap_state_artifacts(root, {})
            broken_handoff = paths.reports_root / "authoritative-handoffs" / "broken.json"
            broken_handoff.parent.mkdir(parents=True, exist_ok=True)
            broken_handoff.write_text(json.dumps({"schema_version": 1, "window_role": "runner"}), encoding="utf-8")
            loop_state = load_loop_state(paths.loop_state)
            loop_state["last_authoritative_handoff_path"] = str(broken_handoff)
            payload, status = research_autoloop.resolve_authoritative_handoff(paths, loop_state)
            self.assertIsNone(payload)
            self.assertEqual(status, "invalid")

    def test_research_loop_contract_stays_pure(self) -> None:
        contract_text = Path("scripts/research_loop_contract.py").read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", contract_text)
        self.assertNotIn("from scripts.research_agent_cli", contract_text)
        self.assertNotIn("from scripts.research_autoloop", contract_text)
        self.assertNotIn("from scripts.research_supervisor", contract_text)

    def test_autoloop_launch_log_keeps_compact_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(root)
            (root / "person_program.md").write_text(
                "# person_program.md\n\n## 1. Core Objective for This Cycle\nBuild the strongest paper evidence package.\n\n## 2. Default Priority Order\nFirst mainline evidence.\n\n## 3. Reader Responsibilities\nThe reader defines the next step.\n\nThis paper direction needs the best evidence package.\n",
                encoding="utf-8",
            )
            paths = bootstrap_state_artifacts(root, {})
            (paths.run_state).write_text(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "phase": "reader",
                "role_context_mode": "isolated",
                "current_objective": "obj",
                "agent_program_ref": "hash",
                "reader_iteration": 0,
                "reader_iteration_cap": 1,
                "runner_iteration": 0,
                "runner_iteration_cap": 1,
                "success_condition": "done",
                "run_id": None,
                "remote_status": "idle",
                "last_result_summary": "",
                "next_action": "reader",
                "repair_count": 0,
                "last_error": None,
                "updated_at": "2026-04-12T00:00:00Z"
            }, ensure_ascii=False, indent=2), encoding="utf-8")

            class Result:
                returncode = 0

            metadata_path = root / ".omx" / "last-launch-metadata.json"

            def fake_run(cmd, cwd=None, **kwargs):
                metadata_path.parent.mkdir(parents=True, exist_ok=True)
                metadata_path.write_text(json.dumps({
                    "prompt_file": str(root / ".omx" / "prompts" / "x.md"),
                    "command_file": str(root / ".omx" / "commands" / "x.cmd.txt"),
                    "canonical_transport_marker": "scripts/research_supervisor.py launch-bash",
                }, ensure_ascii=False), encoding="utf-8")
                return Result()

            with patch("scripts.research_autoloop.subprocess.run", return_value=Result()), \
                 patch("scripts.research_autoloop.time.sleep", return_value=None), \
                 patch("sys.argv", ["research_autoloop.py", "--workdir", str(root), "--hours", "0.0001", "--max-runs", "1", "--ignore-state"]):
                from scripts import research_autoloop
                with patch("scripts.research_autoloop.subprocess.run", side_effect=fake_run):
                    research_autoloop.main()

            log_file = max((root / ".omx" / "autoloop").glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
            lines = log_file.read_text(encoding="utf-8").strip().splitlines()
            launch = json.loads(lines[0])
            self.assertIn("cmd_summary", launch)
            self.assertNotIn("cmd", launch)
            self.assertIn("launch_metadata_path", launch)
            self.assertEqual(launch["canonical_transport_marker"], "scripts/research_supervisor.py launch-bash")
            completed = json.loads(lines[1])
            self.assertIn("launch_metadata", completed)
            self.assertIn("command_file", completed["launch_metadata"])

    def test_ignore_state_resets_run_state_and_observability_for_new_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(root)
            (root / "person_program.md").write_text(
                "# person_program.md\n\n## 1. Core Objective for This Cycle\nBuild the strongest paper evidence package.\n\n## 2. Default Priority Order\nFirst mainline evidence.\n\n## 3. Reader Responsibilities\nThe reader defines the next step.\n\nThis paper direction needs the best evidence package.\n",
                encoding="utf-8",
            )
            config = load_project_config(root)
            paths = bootstrap_state_artifacts(root, config)
            stale_run_state = load_run_state(paths.run_state)
            stale_run_state.update({
                "phase": "watch",
                "next_action": "watch",
                "runner_iteration": 1,
                "current_objective": "old objective",
                "pending_human_prompt": {"target": "runner", "text": "old prompt", "created_at": "2026-04-14T00:00:00Z"},
                "last_error": "stale error",
            })
            paths.run_state.write_text(json.dumps(stale_run_state, ensure_ascii=False, indent=2), encoding="utf-8")
            paths.agent_observability.write_text(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "segments": [{
                    "segment_id": "old-seg",
                    "role": "runner",
                    "status": "completed",
                    "task": "Old task",
                }],
                "updated_at": "2026-04-14T00:00:00Z",
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            paths.watch_snapshot.write_text(json.dumps({
                **default_watch_snapshot(),
                "watch_status": "synced",
                "runner_active": True,
            }, ensure_ascii=False, indent=2), encoding="utf-8")

            with patch("sys.argv", ["research_autoloop.py", "--workdir", str(root), "--hours", "0.0001", "--max-runs", "0", "--ignore-state"]):
                from scripts import research_autoloop
                rc = research_autoloop.main()

            self.assertEqual(rc, 0)
            final_run_state = load_run_state(paths.run_state)
            self.assertEqual(final_run_state["phase"], "reader")
            self.assertEqual(final_run_state["next_action"], "reader")
            self.assertEqual(final_run_state["runner_iteration"], 0)
            self.assertEqual(final_run_state["current_objective"], "")
            self.assertIsNone(final_run_state["pending_human_prompt"])
            self.assertIsNone(final_run_state["last_error"])
            final_observability = read_json(paths.agent_observability)
            self.assertEqual(final_observability["segments"], [])
            final_loop_state = load_loop_state(paths.loop_state)
            self.assertEqual(final_loop_state["next_agent"], "reader")
            self.assertEqual(final_loop_state["last_transition_reason"], "ignore_state_fresh_start")
            final_snapshot = read_json(paths.watch_snapshot)
            self.assertEqual(final_snapshot["watch_status"], "idle")
            self.assertFalse(final_snapshot["runner_active"])


if __name__ == "__main__":
    unittest.main()
