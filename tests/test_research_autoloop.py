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
    compute_prompt_contract_hash,
    default_task_state,
    default_watch_snapshot,
    load_task_state,
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
            bad = default_task_state({})
            bad["schema_version"] = 999
            paths.task_state.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_task_state(paths.task_state)

    def test_missing_required_loop_state_key_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(root)
            (root / "person_program.md").write_text(
                "# person_program.md\n\n## 1. Core Objective for This Cycle\nBuild the strongest paper evidence package.\n\n## 2. Default Priority Order\nFirst mainline evidence.\n\n## 3. Reader Responsibilities\nThe reader defines the next step.\n\nThis paper direction needs the best evidence package.\n",
                encoding="utf-8",
            )
            paths = bootstrap_state_artifacts(root, {})
            bad = default_task_state({})
            bad.pop("updated_at")
            paths.task_state.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_task_state(paths.task_state)

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

    def test_advance_run_state_after_local_running_sets_execution_status(self) -> None:
        run_state = {
            "phase": "watch",
            "runner_iteration": 0,
            "runner_iteration_cap": 1,
            "repair_count": 0,
            "remote_status": "running",
            "execution_backend": "local",
            "execution_status": "running",
            "last_result_summary": "",
            "next_action": "watch",
        }
        next_state = advance_run_state_after_watch(run_state, {
            "backend": "local",
            "watch_status": "running",
            "local_evidence_paths": None,
        })
        self.assertEqual(next_state["phase"], "watch")
        self.assertEqual(next_state["execution_backend"], "local")
        self.assertEqual(next_state["execution_status"], "running")

    def test_advance_run_state_after_local_synced_records_execution_status(self) -> None:
        run_state = {
            "phase": "watch",
            "runner_iteration": 1,
            "runner_iteration_cap": 1,
            "repair_count": 0,
            "remote_status": "running",
            "execution_backend": "local",
            "execution_status": "running",
            "last_result_summary": "",
            "next_action": "watch",
        }
        next_state = advance_run_state_after_watch(run_state, {
            "backend": "local",
            "watch_status": "synced",
            "local_evidence_paths": {"summary.json": "results/summary.json"},
        })
        self.assertEqual(next_state["phase"], "reader")
        self.assertEqual(next_state["remote_status"], "synced")
        self.assertEqual(next_state["runner_done_reason"], "cap_exhausted")

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
        hash_from_autoloop_basis = compute_prompt_contract_hash("person-a", "agent-a", "runner", run_state)
        hash_from_launcher_basis = compute_prompt_contract_hash("person-a", "agent-a", "runner", run_state)
        self.assertEqual(hash_from_autoloop_basis, hash_from_launcher_basis)

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
            (paths.task_state).write_text(json.dumps({
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
            stale_run_state = load_task_state(paths.task_state)
            stale_run_state.update({
                "phase": "watch",
                "next_action": "watch",
                "runner_iteration": 1,
                "current_objective": "old objective",
                "pending_human_prompt": {"target": "runner", "text": "old prompt", "created_at": "2026-04-14T00:00:00Z"},
                "last_error": "stale error",
            })
            paths.task_state.write_text(json.dumps(stale_run_state, ensure_ascii=False, indent=2), encoding="utf-8")
            paths.watch_snapshot.write_text(json.dumps({
                **default_watch_snapshot(),
                "watch_status": "synced",
                "runner_active": True,
            }, ensure_ascii=False, indent=2), encoding="utf-8")

            with patch("sys.argv", ["research_autoloop.py", "--workdir", str(root), "--hours", "0.0001", "--max-runs", "0", "--ignore-state"]):
                from scripts import research_autoloop
                rc = research_autoloop.main()

            self.assertEqual(rc, 0)
            final_run_state = load_task_state(paths.task_state)
            self.assertEqual(final_run_state["phase"], "reader")
            self.assertEqual(final_run_state["next_action"], "reader")
            self.assertEqual(final_run_state["runner_iteration"], 0)
            self.assertEqual(final_run_state["current_objective"], "")
            self.assertIsNone(final_run_state["pending_human_prompt"])
            self.assertIsNone(final_run_state["last_error"])
            final_task_state_check = load_task_state(paths.task_state)
            self.assertEqual(final_task_state_check["window_role"], "reader")
            self.assertEqual(final_task_state_check["next_action"], "reader")
            final_snapshot = read_json(paths.watch_snapshot)
            self.assertEqual(final_snapshot["watch_status"], "idle")
            self.assertFalse(final_snapshot["runner_active"])

    def test_autoloop_watch_phase_uses_local_watcher_for_local_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "research_agent.toml").write_text(
                """
default_hours = 10
default_max_runs = 30
default_poll_seconds = 1

[execution]
backend = "local"

[local]
result_dir = "results"
pid_dir = ".omx/state/local-runs"

[artifacts]
person_program = "person_program.md"
agent_program = "agent_program.md"
loop_state = ".omx/state/research_loop_state.json"
watch_snapshot = ".omx/state/research_watch_snapshot.json"
watch_events = ".omx/state/research_watch_events.jsonl"
run_state = ".omx/state/run-state.json"
ai_worklog = ".omx/logs/ai-worklog.md"
""".strip(),
                encoding="utf-8",
            )
            (root / "person_program.md").write_text(
                "# person_program.md\n\n## 1. Core Objective for This Cycle\nBuild the strongest paper evidence package.\n\n## 2. Default Priority Order\nFirst mainline evidence.\n\n## 3. Reader Responsibilities\nThe reader defines the next step.\n\nThis paper direction needs the best evidence package.\n",
                encoding="utf-8",
            )
            config = load_project_config(root)
            paths = bootstrap_state_artifacts(root, config)
            run_state = load_task_state(paths.task_state)
            run_state.update({
                "phase": "watch",
                "next_action": "watch",
                "run_id": "local-r1",
                "execution_backend": "local",
                "execution_status": "running",
                "runner_iteration": 1,
                "runner_iteration_cap": 1,
            })
            paths.task_state.write_text(json.dumps(run_state, ensure_ascii=False, indent=2), encoding="utf-8")

            def fake_watch_local(**kwargs):
                self.assertTrue(str(kwargs["metadata_path"]).endswith("local-r1.json"))
                return {
                    "schema_version": SCHEMA_VERSION,
                    "assignment_id": "run-state",
                    "run_id": "local-r1",
                    "backend": "local",
                    "watch_status": "synced",
                    "runner_active": False,
                    "supervisor_polling": False,
                    "remote_screen_names": [],
                    "remote_jsons": [],
                    "local_evidence_paths": {"summary.json": str(root / "results" / "summary.json")},
                    "last_remote_activity_at": None,
                    "failure_reason": None,
                    "updated_at": "2026-04-27T00:00:00Z",
                }

            with patch("sys.argv", ["research_autoloop.py", "--workdir", str(root), "--hours", "0.0001", "--max-runs", "1"]), \
                 patch("scripts.research_autoloop.research_supervisor.watch_local", side_effect=fake_watch_local) as local_watch, \
                 patch("scripts.research_autoloop.research_supervisor.watch_remote", side_effect=AssertionError("watch_remote should not run for local backend")):
                from scripts import research_autoloop
                rc = research_autoloop.main()

            self.assertEqual(rc, 0)
            self.assertEqual(local_watch.call_count, 1)
            final_run_state = load_task_state(paths.task_state)
            self.assertEqual(final_run_state["phase"], "reader")
            self.assertEqual(final_run_state["remote_status"], "synced")


if __name__ == "__main__":
    unittest.main()
