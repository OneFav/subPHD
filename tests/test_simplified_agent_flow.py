from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import research_agent_cli
from scripts.research_loop_contract import bootstrap_state_artifacts, load_task_state, atomic_write_json


class SimplifiedAgentCliFlowTests(unittest.TestCase):
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
run_state = ".omx/state/run-state.json"
ai_worklog = ".omx/logs/ai-worklog.md"
""".strip(),
            encoding="utf-8",
        )

    def seed_files(self, root: Path) -> None:
        (root / "person_program.md").write_text(
            "# person_program.md\n\n## 1. Core Objective for This Cycle\nBuild the strongest paper evidence package.\n\n## 2. Default Priority Order\nFirst mainline evidence.\n\n## 3. Reader Responsibilities\nThe reader defines the next step.\n\nThis paper direction needs the best evidence package.\n",
            encoding="utf-8",
        )
        (root / "agent_program.md").write_text(
            "# agent_program.md\n\n## Current Strategy\n- Reader keeps current strategy.\n\n## Revision Suggestions\n- None yet.\n",
            encoding="utf-8",
        )

    def test_build_role_prompt_contains_current_run_state(self) -> None:
        prompt = research_agent_cli.build_role_prompt(
            role="reader",
            person_program="person_summary",
            agent_program="agent_summary",
            person_program_full="# person",
            agent_program_full="# agent",
            task_state={"phase": "reader", "current_objective": "obj", "runner_iteration": 0},
            poll_seconds=300,
            report_path="C:/repo/.omx/reports/final.md",
            supervisor_template="python scripts/research_supervisor.py watch",
            legacy_task=None,
        )
        self.assertIn("CURRENT TASK STATE", prompt)
        self.assertIn("current_objective", prompt)
        self.assertNotIn("CURRENT ASSIGNMENT", prompt)
        self.assertIn("Reader read whitelist", prompt)
        self.assertIn("person_program.md", prompt)
        self.assertIn("task-state.json", prompt)

    def test_runner_prompt_mentions_runner_owned_state_switch(self) -> None:
        prompt = research_agent_cli.build_role_prompt(
            role="runner",
            person_program="person_summary",
            agent_program="agent_summary",
            person_program_full="# person",
            agent_program_full="# agent",
            task_state={"phase": "runner", "current_objective": "obj", "runner_iteration": 1, "runner_iteration_cap": 1},
            poll_seconds=300,
            report_path="C:/repo/.omx/reports/final.md",
            supervisor_template="python scripts/research_supervisor.py watch",
            legacy_task=None,
        )
        self.assertIn("Runner-owned state transition", prompt)
        self.assertIn("set `task-state.json` back to `reader`", prompt)
        self.assertIn("may implement or modify local code", prompt)
        self.assertIn("Experiment launch and watch behavior must follow the configured execution backend", prompt)

    def test_main_appends_ai_worklog_for_reader_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(root)
            self.seed_files(root)
            config = research_agent_cli.load_project_config(root)
            paths = bootstrap_state_artifacts(root, config)
            run_state = load_task_state(paths.task_state)
            run_state.update({
                "current_objective": "reader objective",
                "reader_iteration": 1,
                "reader_iteration_cap": 5,
                "runner_iteration": 0,
                "runner_iteration_cap": 2,
                "success_condition": "score > 0.8",
                "next_action": "reader",
            })
            atomic_write_json(paths.task_state, run_state)

            class Result:
                returncode = 0

            with patch("scripts.research_agent_cli.subprocess.run", return_value=Result()), \
                 patch("scripts.research_agent_cli.resolve_launcher_path", return_value="omx"), \
                 patch("sys.argv", ["research_agent_cli.py", "--workdir", str(root), "--role", "reader"]):
                rc = research_agent_cli.main()

            self.assertEqual(rc, 0)
            final_state = load_task_state(paths.task_state)
            self.assertEqual(final_state["phase"], "runner")
            self.assertEqual(final_state["next_action"], "runner")
            text = paths.ai_worklog.read_text(encoding="utf-8")
            self.assertIn("reader", text)
            self.assertIn("reader objective", text)
            self.assertIn("score > 0.8", text)

    def test_main_forces_runner_handoff_to_reader_at_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(root)
            self.seed_files(root)
            config = research_agent_cli.load_project_config(root)
            paths = bootstrap_state_artifacts(root, config)
            run_state = load_task_state(paths.task_state)
            run_state.update({
                "phase": "runner",
                "current_objective": "runner objective",
                "reader_iteration": 1,
                "reader_iteration_cap": 5,
                "runner_iteration": 2,
                "runner_iteration_cap": 2,
                "success_condition": "score > 0.8",
                "next_action": "watch",
            })
            atomic_write_json(paths.task_state, run_state)

            class Result:
                returncode = 0

            with patch("scripts.research_agent_cli.subprocess.run", return_value=Result()), \
                 patch("scripts.research_agent_cli.resolve_launcher_path", return_value="omx"), \
                 patch("sys.argv", ["research_agent_cli.py", "--workdir", str(root), "--role", "runner"]):
                rc = research_agent_cli.main()

            self.assertEqual(rc, 0)
            final_state = load_task_state(paths.task_state)
            # New behavior: watch is respected even when cap exhausted
            self.assertEqual(final_state["phase"], "runner")
            self.assertEqual(final_state["next_action"], "watch")

    def test_normalize_runner_respects_watch_phase(self):
        from scripts.research_agent_cli import normalize_post_role_run_state
        state = {"phase": "watch", "next_action": "watch", "runner_iteration": 0, "runner_iteration_cap": 4}
        result = normalize_post_role_run_state("runner", state)
        self.assertEqual(result["phase"], "watch")

    def test_normalize_runner_respects_runner_phase_when_cap_not_exhausted(self):
        from scripts.research_agent_cli import normalize_post_role_run_state
        state = {"phase": "runner", "next_action": "runner", "runner_iteration": 1, "runner_iteration_cap": 4}
        result = normalize_post_role_run_state("runner", state)
        self.assertEqual(result["phase"], "runner")

    def test_normalize_runner_respects_terminal_phase(self):
        from scripts.research_agent_cli import normalize_post_role_run_state
        state = {"phase": "done", "next_action": "done", "runner_iteration": 3, "runner_iteration_cap": 4}
        result = normalize_post_role_run_state("runner", state)
        self.assertEqual(result["phase"], "done")

    def test_normalize_runner_goes_reader_when_cap_exhausted(self):
        from scripts.research_agent_cli import normalize_post_role_run_state
        state = {"phase": "runner", "next_action": "runner", "runner_iteration": 4, "runner_iteration_cap": 4}
        result = normalize_post_role_run_state("runner", state)
        self.assertEqual(result["phase"], "reader")

    def test_normalize_reader_always_transitions_to_runner(self):
        from scripts.research_agent_cli import normalize_post_role_run_state
        state = {"phase": "reader", "next_action": "reader"}
        result = normalize_post_role_run_state("reader", state)
        self.assertEqual(result["phase"], "runner")

    def test_consume_pending_human_prompt_moves_to_applied(self):
        from scripts.research_agent_cli import consume_pending_human_prompt_if_matched
        state = {"pending_human_prompt": {"target": "runner", "text": "check OOM"}}
        result = consume_pending_human_prompt_if_matched(state, matched_prompt=state["pending_human_prompt"])
        self.assertNotIn("pending_human_prompt", result)
        self.assertEqual(result["last_applied_human_prompt"]["text"], "check OOM")


if __name__ == "__main__":
    unittest.main()
