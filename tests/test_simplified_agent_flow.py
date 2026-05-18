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
            # Reader stays in reader phase for direct execution (no forced transition to runner)
            self.assertEqual(final_state["phase"], "reader")
            self.assertEqual(final_state["next_action"], "reader")
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

    def test_normalize_runner_must_not_declare_done_or_abandoned(self):
        from scripts.research_agent_cli import normalize_post_role_run_state
        for phase in ("done", "abandoned"):
            state = {"phase": phase, "next_action": phase, "runner_iteration": 3, "runner_iteration_cap": 4}
            result = normalize_post_role_run_state("runner", state)
            self.assertEqual(result["phase"], "reader",
                             f"runner setting phase={phase} must be overridden to reader")

    def test_normalize_runner_respects_needs_human(self):
        from scripts.research_agent_cli import normalize_post_role_run_state
        state = {"phase": "needs_human", "next_action": "needs_human", "runner_iteration": 3, "runner_iteration_cap": 4}
        result = normalize_post_role_run_state("runner", state)
        self.assertEqual(result["phase"], "needs_human")

    def test_normalize_runner_goes_reader_when_cap_exhausted(self):
        from scripts.research_agent_cli import normalize_post_role_run_state
        state = {"phase": "runner", "next_action": "runner", "runner_iteration": 4, "runner_iteration_cap": 4}
        result = normalize_post_role_run_state("runner", state)
        self.assertEqual(result["phase"], "reader")

    # ── Sprint-contract-driven runner iteration (non-watch path) ──

    def test_normalize_runner_iterates_when_success_not_met_and_budget_remains(self):
        """Runner stays runner when sprint contract metrics don't meet success condition yet."""
        from scripts.research_agent_cli import normalize_post_role_run_state
        state = {
            "phase": "reader",  # runner forgot to set phase
            "runner_iteration": 0,
            "runner_iteration_cap": 3,
            "sprint_contract": {
                "sprint_type": "construction",
                "success_condition": {
                    "mode": "all",
                    "conditions": [{"metric": "target_accuracy", "op": ">=", "threshold": 0.9}],
                },
                "metrics": {"target_accuracy": 0.72},  # not met
            },
        }
        result = normalize_post_role_run_state("runner", state)
        self.assertEqual(result["phase"], "runner")
        self.assertEqual(result["next_action"], "runner")
        self.assertEqual(result["runner_iteration"], 1)  # incremented
        self.assertIsNone(result.get("runner_done_reason"))

    def test_normalize_runner_marks_done_when_sprint_success_met(self):
        """Runner sets phase=done when sprint contract success condition is satisfied."""
        from scripts.research_agent_cli import normalize_post_role_run_state
        state = {
            "phase": "reader",
            "runner_iteration": 1,
            "runner_iteration_cap": 3,
            "sprint_contract": {
                "sprint_type": "construction",
                "success_condition": {
                    "mode": "all",
                    "conditions": [
                        {"metric": "target_accuracy", "op": ">=", "threshold": 0.9},
                    ],
                },
                "metrics": {"target_accuracy": 0.94},
            },
        }
        result = normalize_post_role_run_state("runner", state)
        self.assertEqual(result["phase"], "done")
        self.assertIn("sprint_success", result.get("runner_done_reason", ""))

    def test_normalize_runner_goes_reader_when_sprint_cap_exhausted(self):
        """Runner goes to reader when success not met and cap exhausted."""
        from scripts.research_agent_cli import normalize_post_role_run_state
        state = {
            "phase": "reader",
            "runner_iteration": 2,  # next increment makes it 3
            "runner_iteration_cap": 3,
            "sprint_contract": {
                "sprint_type": "construction",
                "success_condition": {
                    "mode": "all",
                    "conditions": [{"metric": "target_accuracy", "op": ">=", "threshold": 0.9}],
                },
                "metrics": {"target_accuracy": 0.72},  # still not met
            },
        }
        result = normalize_post_role_run_state("runner", state)
        # runner_iteration 2 + 1 = 3, cap is 3, so exhausted
        self.assertEqual(result["runner_iteration"], 3)
        self.assertEqual(result["phase"], "reader")
        self.assertIn("cap_exhausted", result.get("runner_done_reason", ""))

    def test_normalize_runner_watch_overrides_sprint_iteration(self):
        """Runner's explicit watch phase passes through regardless of sprint state."""
        from scripts.research_agent_cli import normalize_post_role_run_state
        state = {
            "phase": "watch",
            "next_action": "watch",
            "runner_iteration": 0,
            "runner_iteration_cap": 3,
            "sprint_contract": {
                "sprint_type": "construction",
                "success_condition": {
                    "mode": "all",
                    "conditions": [{"metric": "target_accuracy", "op": ">=", "threshold": 0.9}],
                },
                "metrics": {"target_accuracy": 0.5},
            },
        }
        result = normalize_post_role_run_state("runner", state)
        # watch takes priority — sprint iteration is not triggered
        self.assertEqual(result["phase"], "watch")

    def test_normalize_runner_without_sprint_contract_falls_back_to_explicit_choice(self):
        """Without a sprint_contract, old fallback behavior still works."""
        from scripts.research_agent_cli import normalize_post_role_run_state
        # Runner explicitly wants runner, cap not exhausted
        state = {"phase": "runner", "runner_iteration": 1, "runner_iteration_cap": 4}
        result = normalize_post_role_run_state("runner", state)
        self.assertEqual(result["phase"], "runner")

        # Cap exhausted → reader
        state2 = {"phase": "runner", "runner_iteration": 4, "runner_iteration_cap": 4}
        result2 = normalize_post_role_run_state("runner", state2)
        self.assertEqual(result2["phase"], "reader")

    def test_normalize_reader_respects_own_phase_choice(self):
        """Reader can stay in reader for direct execution; framework respects the choice."""
        from scripts.research_agent_cli import normalize_post_role_run_state
        # Reader explicitly stays reader → respected
        state = {"phase": "reader", "next_action": "reader"}
        result = normalize_post_role_run_state("reader", state)
        self.assertEqual(result["phase"], "reader")

    def test_normalize_reader_can_set_runner_phase(self):
        """Reader can still delegate to runner when it chooses."""
        from scripts.research_agent_cli import normalize_post_role_run_state
        state = {"phase": "runner", "next_action": "runner"}
        result = normalize_post_role_run_state("reader", state)
        self.assertEqual(result["phase"], "runner")

    def test_normalize_reader_defaults_to_runner_when_no_phase_set(self):
        """If reader doesn't set a phase, default to runner."""
        from scripts.research_agent_cli import normalize_post_role_run_state
        state = {}
        result = normalize_post_role_run_state("reader", state)
        self.assertEqual(result["phase"], "runner")

    def test_consume_pending_human_prompt_moves_to_applied(self):
        from scripts.research_agent_cli import consume_pending_human_prompt_if_matched
        state = {"pending_human_prompt": {"target": "runner", "text": "check OOM"}}
        result = consume_pending_human_prompt_if_matched(state, matched_prompt=state["pending_human_prompt"])
        self.assertNotIn("pending_human_prompt", result)
        self.assertEqual(result["last_applied_human_prompt"]["text"], "check OOM")


    # ──────────────────────────────────────────────
    # Task 2: Reader role Sprint Contract assertions
    # ──────────────────────────────────────────────

    def test_reader_role_surface_mandates_metric_in_success_condition(self):
        """Reader 角色表面要求 success_condition 必须包含 metric 条件"""
        surface = Path("roles/reader/AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("metric", surface.lower())
        self.assertIn("success_condition", surface)
        self.assertIn("artifact", surface.lower())

    def test_reader_role_surface_has_sprint_types(self):
        """Reader 角色表面定义了 sprint_type 分类"""
        surface = Path("roles/reader/AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("sprint_type", surface)
        self.assertIn("diagnostic", surface)
        self.assertIn("construction", surface)
        self.assertIn("sweep", surface)
        self.assertIn("terminal_collection", surface)

    def test_reader_role_surface_has_iterability_check(self):
        """Reader 角色表面要求可迭代性自检"""
        surface = Path("roles/reader/AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("iterab", surface.lower())  # iterability / iterable

    def test_reader_role_surface_no_longer_sets_done_directly(self):
        """Reader 角色表面不再手动设 phase=done（autoloop 处理）"""
        surface = Path("roles/reader/AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("autoloop", surface.lower())
        self.assertIn("evaluates", surface.lower())

    # ──────────────────────────────────────────────
    # Task 1: Runner role Sprint Contract assertions
    # ──────────────────────────────────────────────

    def test_runner_role_surface_mandates_metrics_increment(self):
        """Runner 角色表面要求每轮更新 sprint_contract.metrics"""
        surface = Path("roles/runner/AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("metrics", surface)
        self.assertIn("sprint_contract", surface)
        self.assertTrue(
            "update" in surface.lower() and "metric" in surface.lower(),
            "Runner role surface must mandate metrics updates"
        )

    def test_runner_role_surface_forbids_done_abandoned(self):
        """Runner 角色表面禁止直接设置 phase=done/abandoned"""
        surface = Path("roles/runner/AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("MUST NOT", surface)
        self.assertNotIn("Sprint succeeded", surface)
        self.assertNotIn("Sprint failed, cannot recover", surface)
        self.assertIn("needs_human", surface.lower())

    def test_runner_role_surface_mentions_research_question(self):
        """Runner 角色表面引导回答 research_question，非完成步骤清单"""
        surface = Path("roles/runner/AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("research_question", surface)
        self.assertIn("hypothesis", surface.lower())

    def test_runner_role_surface_has_simplified_phase_table(self):
        """Runner 角色表面的 phase 转换表只含 watch/runner/reader/needs_human"""
        surface = Path("roles/runner/AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("watch", surface.lower())
        self.assertIn("reader", surface.lower())
        self.assertNotIn('"done"', surface)
        self.assertNotIn('"abandoned"', surface)

    # ──────────────────────────────────────────────
    # Task 3: Sprint Contract validation tests
    # ──────────────────────────────────────────────

    def test_validate_sprint_contract_rejects_pure_artifact_non_terminal(self):
        """non-terminal sprint 不允许纯 artifact success_condition"""
        from scripts.research_agent_cli import validate_sprint_contract
        sc = {
            "sprint_id": "sprint-1",
            "sprint_type": "diagnostic",
            "success_condition": {
                "mode": "all",
                "conditions": [
                    {"artifact": "results/x.json", "exists": True}
                ]
            }
        }
        ok, warnings = validate_sprint_contract(sc)
        self.assertFalse(ok)
        self.assertTrue(any("metric" in w.lower() for w in warnings))

    def test_validate_sprint_contract_accepts_metric_condition(self):
        """包含 metric 条件的 success_condition 应该是有效的"""
        from scripts.research_agent_cli import validate_sprint_contract
        sc = {
            "sprint_id": "sprint-1",
            "sprint_type": "diagnostic",
            "success_condition": {
                "mode": "all",
                "conditions": [
                    {"metric": "acc", "op": ">=", "threshold": 0.9},
                    {"artifact": "results/x.json", "exists": True}
                ]
            }
        }
        ok, warnings = validate_sprint_contract(sc)
        self.assertTrue(ok)

    def test_validate_sprint_contract_allows_pure_artifact_for_terminal(self):
        """terminal_collection 类型允许纯 artifact success_condition"""
        from scripts.research_agent_cli import validate_sprint_contract
        sc = {
            "sprint_id": "sprint-final",
            "sprint_type": "terminal_collection",
            "success_condition": {
                "mode": "all",
                "conditions": [
                    {"artifact": "results/paper_packet.json", "exists": True}
                ]
            }
        }
        ok, warnings = validate_sprint_contract(sc)
        self.assertTrue(ok)

    def test_validate_sprint_contract_handles_legacy_string_condition(self):
        """旧版 string success_condition 返回警告但不阻塞"""
        from scripts.research_agent_cli import validate_sprint_contract
        sc = {
            "sprint_id": "sprint-1",
            "sprint_type": "diagnostic",
            "success_condition": "causal probe specificity delta >= 0.05"
        }
        ok, warnings = validate_sprint_contract(sc)
        # Legacy string: should warn about missing structured condition
        self.assertTrue(ok)  # Not a hard failure
        self.assertTrue(len(warnings) > 0)

    def test_validate_sprint_contract_requires_sprint_type(self):
        """缺少 sprint_type 的 sprint 应该产生警告"""
        from scripts.research_agent_cli import validate_sprint_contract
        sc = {
            "sprint_id": "sprint-1",
            "success_condition": {
                "mode": "all",
                "conditions": [
                    {"metric": "acc", "op": ">=", "threshold": 0.9}
                ]
            }
        }
        ok, warnings = validate_sprint_contract(sc)
        self.assertFalse(ok)
        self.assertTrue(any("sprint_type" in w.lower() for w in warnings))


if __name__ == "__main__":
    unittest.main()
