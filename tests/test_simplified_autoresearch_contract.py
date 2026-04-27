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
            self.assertTrue(hasattr(paths, "run_state"))
            state = contract.load_run_state(paths.run_state)
            self.assertEqual(state["phase"], "reader")
            self.assertEqual(state["role_context_mode"], "isolated")
            self.assertIn("agent_program_ref", state)

    def test_ensure_role_surfaces_bootstraps_subphd_reader_and_runner_skill_suite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(root)
            self.seed_program_files(root)
            paths = contract.bootstrap_state_artifacts(root, {"artifacts": {}})
            expected_skills = [
                paths.reader_role_root / "skills" / "reader-handoff" / "SKILL.md",
                paths.reader_role_root / "skills" / "experiment-plan" / "SKILL.md",
                paths.reader_role_root / "skills" / "analyze-results" / "SKILL.md",
                paths.reader_role_root / "skills" / "result-to-claim" / "SKILL.md",
                paths.runner_role_root / "skills" / "runner-implementation" / "SKILL.md",
                paths.runner_role_root / "skills" / "experiment-bridge" / "SKILL.md",
                paths.runner_role_root / "skills" / "monitor-experiment" / "SKILL.md",
                paths.runner_role_root / "skills" / "training-check" / "SKILL.md",
                paths.runner_role_root / "skills" / "local-experiment" / "SKILL.md",
                paths.runner_role_root / "skills" / "local-watch" / "SKILL.md",
            ]
            for skill_path in expected_skills:
                self.assertTrue(skill_path.exists(), skill_path)

    def test_resolve_execution_backend_defaults_to_ssh_when_remote_config_exists(self) -> None:
        config = {"remote": {"host": "host", "ssh_key": "key", "remote_code_dir": "/code"}}
        self.assertEqual(contract.resolve_execution_backend(config), "ssh")

    def test_resolve_execution_backend_uses_explicit_local(self) -> None:
        config = {"execution": {"backend": "local"}, "remote": {"host": "host"}}
        self.assertEqual(contract.resolve_execution_backend(config), "local")

    def test_resolve_execution_backend_rejects_unknown_backend(self) -> None:
        with self.assertRaises(ValueError):
            contract.resolve_execution_backend({"execution": {"backend": "docker"}})

    def test_default_run_state_includes_execution_backend_and_status(self) -> None:
        state = contract.default_run_state({"execution": {"backend": "local"}})
        self.assertEqual(state["execution_backend"], "local")
        self.assertEqual(state["execution_status"], "idle")
        self.assertEqual(state["remote_status"], "idle")

    def test_default_remaining_budget_prefers_local_gpu_count_in_local_mode(self) -> None:
        budget = contract.default_remaining_budget({
            "execution": {"backend": "local"},
            "local": {"gpu_count": 2},
            "remote": {"gpu_count": 8},
        })
        self.assertEqual(budget["gpu_count"], 2)

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

    def test_merge_observability_sidecar_marks_missing_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            canonical_path = Path(tmp) / ".omx" / "state" / "agent-observability.json"
            merged = contract.merge_observability_sidecar(
                canonical_path,
                {
                    "segment_id": "seg-1",
                    "role": "runner",
                    "status": "completed",
                },
                Path(tmp) / ".omx" / "reports" / "agent-observability-seg-1.json",
            )
            self.assertEqual(merged["segments"][0]["merge_status"], "not_found")

    def test_resolve_artifact_paths_includes_agent_observability(self) -> None:
        root = Path("C:/repo")
        paths = contract.resolve_artifact_paths(root, {"artifacts": {}})
        self.assertTrue(hasattr(paths, "agent_observability"))
        self.assertEqual(paths.agent_observability, (root / ".subphd/state/agent-observability.json").resolve())

    def test_validate_run_state_accepts_pending_human_prompt(self) -> None:
        run_state = contract.default_run_state({})
        run_state["pending_human_prompt"] = {
            "target": "runner",
            "text": "Focus on the regression cause first.",
            "created_at": "2026-04-14T00:00:00Z",
        }
        validated = contract.validate_run_state(run_state)
        self.assertEqual(validated["pending_human_prompt"]["target"], "runner")

    def test_build_prompt_render_state_hides_unmatched_prompt(self) -> None:
        run_state = contract.default_run_state({})
        run_state["pending_human_prompt"] = {
            "target": "runner",
            "text": "Runner-only note",
            "created_at": "2026-04-14T00:00:00Z",
        }
        reader_state, reader_prompt = contract.build_prompt_render_state(run_state, "reader")
        runner_state, runner_prompt = contract.build_prompt_render_state(run_state, "runner")
        self.assertNotIn("pending_human_prompt", reader_state)
        self.assertIsNone(reader_prompt)
        self.assertNotIn("pending_human_prompt", runner_state)
        self.assertEqual(runner_prompt["text"], "Runner-only note")

    def test_rendered_prompt_hash_matches_canonical_hash_when_no_pending_prompt(self) -> None:
        run_state = contract.default_run_state({})
        canonical = contract.compute_prompt_contract_hash("person", "agent", "reader", run_state)
        rendered = contract.compute_rendered_prompt_contract_hash("person", "agent", "reader", run_state)
        self.assertEqual(canonical, rendered)

    def test_loop_state_backfills_role_local_window_policy_fields(self) -> None:
        legacy = contract.default_loop_state({})
        loaded = contract.validate_loop_state(legacy)
        self.assertIn("big_round_id", loaded)
        self.assertIn("window_role", loaded)
        self.assertIn("role_window_id", loaded)
        self.assertEqual(loaded["resume_budget"], 3)
        self.assertEqual(loaded["resume_count"], 0)

    def test_prompt_contract_hash_changes_when_authoritative_handoff_changes(self) -> None:
        run_state = contract.default_run_state({})
        handoff_a = {"handoff_summary_text": "alpha", "authoritative_artifacts": ["a.json"]}
        handoff_b = {"handoff_summary_text": "beta", "authoritative_artifacts": ["a.json"]}
        hash_a = contract.compute_rendered_prompt_contract_hash(
            "person",
            "agent",
            "reader",
            run_state,
            authoritative_handoff=handoff_a,
        )
        hash_b = contract.compute_rendered_prompt_contract_hash(
            "person",
            "agent",
            "reader",
            run_state,
            authoritative_handoff=handoff_b,
        )
        self.assertNotEqual(hash_a, hash_b)

    def test_merge_observability_sidecar_merges_valid_sidecar_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical_path = root / ".omx" / "state" / "agent-observability.json"
            sidecar_path = root / ".omx" / "reports" / "agent-observability-seg-1.json"
            sidecar_path.parent.mkdir(parents=True, exist_ok=True)
            sidecar_path.write_text(json.dumps({
                "segment_id": "seg-1",
                "role": "runner",
                "task": "Patch the launcher hash flow",
                "started_at": "2026-04-14T00:00:00Z",
                "eta": "2026-04-14T01:00:00Z",
                "expected_output": "green tests",
                "why": "prevent prompt leakage",
                "status": "completed",
                "completion_summary": "Validated the prompt hash flow and preserved resume compatibility.",
                "ended_at": "2026-04-14T00:40:00Z",
                "updated_at": "2026-04-14T00:30:00Z",
            }), encoding="utf-8")
            merged = contract.merge_observability_sidecar(
                canonical_path,
                {
                    "segment_id": "seg-1",
                    "role": "runner",
                    "status": "completed",
                },
                sidecar_path,
            )
            segment = merged["segments"][0]
            self.assertEqual(segment["merge_status"], "merged")
            self.assertEqual(segment["task"], "Patch the launcher hash flow")
            self.assertEqual(segment["expected_output"], "green tests")
            self.assertEqual(segment["started_at"], "2026-04-14T00:00:00Z")
            self.assertEqual(segment["ended_at"], "2026-04-14T00:40:00Z")
            self.assertEqual(segment["status"], "completed")
            self.assertIn("resume compatibility", segment["completion_summary"])

    def test_merge_observability_sidecar_accepts_start_phase_sidecar_without_end_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical_path = root / ".omx" / "state" / "agent-observability.json"
            sidecar_path = root / ".omx" / "reports" / "agent-observability-seg-2.json"
            sidecar_path.parent.mkdir(parents=True, exist_ok=True)
            sidecar_path.write_text(json.dumps({
                "segment_id": "seg-2",
                "role": "reader",
                "task": "Read the newest remote metrics package",
                "started_at": "2026-04-14T02:00:00Z",
                "expected_output": "A handoff-ready diagnosis",
                "why": "Decide whether the loop should stay in runner or return to reader",
                "status": "running",
                "updated_at": "2026-04-14T02:01:00Z",
            }), encoding="utf-8")
            merged = contract.merge_observability_sidecar(
                canonical_path,
                {
                    "segment_id": "seg-2",
                    "role": "reader",
                    "status": "running",
                },
                sidecar_path,
            )
            segment = merged["segments"][0]
            self.assertEqual(segment["merge_status"], "merged")
            self.assertEqual(segment["status"], "running")
            self.assertEqual(segment["started_at"], "2026-04-14T02:00:00Z")
            self.assertNotIn("ended_at", segment)

    def test_bootstrap_imports_legacy_omx_state_into_new_canonical_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(root)
            self.seed_program_files(root)
            legacy_run_state = root / ".omx" / "state" / "run-state.json"
            legacy_run_state.parent.mkdir(parents=True, exist_ok=True)
            legacy_run_state.write_text(json.dumps({
                "schema_version": 1,
                "phase": "runner",
                "role_context_mode": "isolated",
                "current_objective": "resume from legacy omx",
                "agent_program_ref": None,
                "reader_iteration": 1,
                "reader_iteration_cap": 30,
                "runner_iteration": 1,
                "runner_iteration_cap": 1,
                "success_condition": "",
                "run_id": None,
                "remote_status": "idle",
                "last_result_summary": "",
                "next_action": "runner",
                "pending_human_prompt": None,
                "repair_count": 0,
                "last_error": None,
                "updated_at": "2026-04-14T00:00:00Z",
            }), encoding="utf-8")
            paths = contract.bootstrap_state_artifacts(root, {"artifacts": {}})
            imported = contract.load_run_state(paths.run_state)
            self.assertEqual(paths.run_state, (root / ".subphd" / "state" / "run-state.json").resolve())
            self.assertEqual(imported["phase"], "runner")
            self.assertEqual(imported["current_objective"], "resume from legacy omx")

    def test_export_omx_compat_artifacts_writes_legacy_shadow_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(root)
            self.seed_program_files(root)
            config = {
                "artifacts": {},
                "runtime": {
                    "root": ".subphd",
                    "compat_omx_export": True,
                },
            }
            paths = contract.bootstrap_state_artifacts(root, config)
            run_state = contract.load_run_state(paths.run_state)
            run_state["current_objective"] = "compat export objective"
            contract.atomic_write_json(paths.run_state, run_state)
            contract.export_omx_compat_artifacts(paths, config)
            legacy_run_state = contract.read_json(root / ".omx" / "state" / "run-state.json")
            self.assertEqual(legacy_run_state["current_objective"], "compat export objective")


if __name__ == "__main__":
    unittest.main()
