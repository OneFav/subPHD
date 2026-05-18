from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.research_agent_cli import (
    build_supervisor_template,
    build_codex_command,
    build_role_prompt,
    consume_pending_human_prompt_if_matched,
    ensure_runner_backend_requirements,
    ensure_runner_remote_requirements,
    run_codex_command,
    write_launch_metadata,
)
from scripts.research_loop_contract import (
    compact_text_summary,
    compute_prompt_contract_hash,
    read_validated_text,
    render_compact_summary,
)


class ResearchAgentCliTests(unittest.TestCase):
    def test_build_role_prompt_does_not_invoke_ralph_skill_prefix(self) -> None:
        prompt = build_role_prompt(
            role="reader",
            person_program="person_summary",
            agent_program="agent_summary",
            person_program_full="# person",
            agent_program_full="# agent",
            task_state={"phase": "reader", "current_objective": "objective-a", "runner_iteration": 0},
            poll_seconds=300,
            report_path="C:/repo/.subphd/reports/final.md",
            supervisor_template="python scripts/research_supervisor.py launch-bash --script-file x.sh",
            legacy_task=None,
        )
        self.assertNotIn("$ralph", prompt)
        self.assertIn("execute the current sub-phd loop step", prompt.lower())

    def test_build_role_prompt_preserves_full_bodies_and_compact_summaries(self) -> None:
        prompt = build_role_prompt(
            role="reader",
            person_program="person_summary",
            agent_program="agent_summary",
            person_program_full="# person",
            agent_program_full="# agent",
            task_state={"phase": "reader", "current_objective": "objective-a", "runner_iteration": 0},
            poll_seconds=300,
            report_path="C:/repo/.omx/reports/final.md",
            supervisor_template="python scripts/research_supervisor.py launch-bash --script-file x.sh",
            legacy_task="legacy",
        )
        self.assertIn("person_summary", prompt)
        self.assertIn("agent_summary", prompt)
        self.assertIn("# person", prompt)
        self.assertIn("# agent", prompt)
        self.assertIn("READER lane", prompt)
        self.assertIn("legacy", prompt)
        self.assertIn("final.md", prompt)
        self.assertIn("CURRENT TASK STATE", prompt)

    def test_build_role_prompt_instructs_runner_to_prune_remote_results_before_watch_sync(self) -> None:
        prompt = build_role_prompt(
            role="runner",
            person_program="person_summary",
            agent_program="agent_summary",
            person_program_full="# person",
            agent_program_full="# agent",
            task_state={
                "phase": "runner",
                "current_objective": "objective-a",
                "runner_iteration": 1,
            },
            poll_seconds=300,
            report_path="C:/repo/.subphd/reports/final.md",
            supervisor_template="python scripts/research_supervisor.py watch",
            legacy_task=None,
        )
        self.assertIn("prune `remote_result_dir`", prompt)
        self.assertIn("delete bulky intermediate or process files", prompt)
        self.assertIn("Leave only the compact core result set", prompt)

    def test_build_role_prompt_selectively_loads_only_needed_reader_skills(self) -> None:
        prompt = build_role_prompt(
            role="reader",
            person_program="person_summary",
            agent_program="agent_summary",
            person_program_full="# person",
            agent_program_full="# agent",
            task_state={
                "phase": "reader",
                "current_objective": "Write the next bounded runner assignment.",
                "reader_iteration": 1,
            },
            poll_seconds=300,
            report_path="C:/repo/.subphd/reports/final.md",
            supervisor_template="python scripts/research_supervisor.py watch",
            legacy_task=None,
        )
        self.assertIn("Activated role-local skills for this turn", prompt)
        self.assertIn("reader-handoff", prompt)
        self.assertIn("Reader Handoff", prompt)
        self.assertNotIn("Experiment Plan", prompt)
        self.assertNotIn("Analyze Results", prompt)
        self.assertNotIn("Result to Claim", prompt)

    def test_build_role_prompt_activates_keyword_matched_reader_skills(self) -> None:
        prompt = build_role_prompt(
            role="reader",
            person_program="person_summary",
            agent_program="agent_summary",
            person_program_full="# person",
            agent_program_full="# agent",
            task_state={
                "phase": "reader",
                "current_objective": "Analyze the latest results and decide what claim is supported.",
                "reader_iteration": 1,
            },
            poll_seconds=300,
            report_path="C:/repo/.subphd/reports/final.md",
            supervisor_template="python scripts/research_supervisor.py watch",
            legacy_task=None,
        )
        self.assertIn("Analyze Results", prompt)
        self.assertIn("Result to Claim", prompt)
        self.assertNotIn("Experiment Plan", prompt)

    def test_build_role_prompt_respects_explicit_active_role_skills(self) -> None:
        prompt = build_role_prompt(
            role="runner",
            person_program="person_summary",
            agent_program="agent_summary",
            person_program_full="# person",
            agent_program_full="# agent\n\nRunner skills: training-check",
            task_state={
                "phase": "runner",
                "current_objective": "Patch the launch script.",
                "runner_iteration": 1,
            },
            poll_seconds=300,
            report_path="C:/repo/.subphd/reports/final.md",
            supervisor_template="python scripts/research_supervisor.py watch",
            legacy_task=None,
        )
        self.assertIn("runner-implementation", prompt)
        self.assertIn("training-check", prompt)
        self.assertIn("Training Check", prompt)
        self.assertNotIn("Monitor Experiment", prompt)

    def test_prompt_contract_hash_changes_when_program_changes(self) -> None:
        hash_a = compute_prompt_contract_hash("person-a", "agent-a", "reader", {"assignment_id": "A1"})
        hash_b = compute_prompt_contract_hash("person-a", "agent-b", "reader", {"assignment_id": "A1"})
        self.assertNotEqual(hash_a, hash_b)

    def test_runner_launch_requires_remote_config(self) -> None:
        with self.assertRaises(ValueError):
            ensure_runner_remote_requirements({"remote": {"host": "x"}})

    def test_runner_backend_requirements_allow_local_without_remote_config(self) -> None:
        ensure_runner_backend_requirements({"execution": {"backend": "local"}, "local": {"result_dir": "results"}})

    def test_runner_backend_requirements_require_remote_config_for_ssh(self) -> None:
        with self.assertRaises(ValueError):
            ensure_runner_backend_requirements({"execution": {"backend": "ssh"}, "remote": {"host": "x"}})

    def test_build_role_prompt_in_local_mode_does_not_say_remote_only(self) -> None:
        prompt = build_role_prompt(
            role="runner",
            person_program="person_summary",
            agent_program="agent_summary",
            person_program_full="# person",
            agent_program_full="# agent",
            task_state={
                "phase": "runner",
                "current_objective": "Run local smoke experiment.",
                "runner_iteration": 1,
                "execution_backend": "local",
            },
            poll_seconds=300,
            report_path="C:/repo/.omx/reports/final.md",
            supervisor_template="python scripts/research_supervisor.py launch --backend local",
            legacy_task=None,
            execution_backend="local",
        )
        self.assertIn("LOCAL execution mode", prompt)
        self.assertIn("Do not require SSH", prompt)
        self.assertNotIn("remain remote-only", prompt)
        self.assertIn("local-experiment", prompt)
        self.assertIn("local-watch", prompt)

    def test_build_supervisor_template_for_local_backend_uses_local_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {
                "execution": {"backend": "local"},
                "local": {
                    "workdir": ".",
                    "result_dir": "results",
                    "log_dir": ".omx/logs/local-runs",
                    "pid_dir": ".omx/state/local-runs",
                },
                "artifacts": {},
            }
            template = build_supervisor_template(root, 5, config)
            self.assertIn("--backend local", template)
            self.assertIn("watch-backend", template)
            self.assertIn("--local-result-dir", template)
            self.assertNotIn("--ssh-key", template)

    def test_write_launch_metadata_records_local_backend_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_path = root / "metadata.json"
            write_launch_metadata(
                metadata_path,
                role="runner",
                rendered_prompt_hash="hash",
                prompt_file=root / "prompt.md",
                command_file=root / "command.txt",
                report_file=root / "report.md",
                execution_backend="local",
            )
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["execution_backend"], "local")
            self.assertIn("--backend local", payload["canonical_transport_marker"])
            self.assertIn("watch-backend --backend local", payload["canonical_watch_marker"])

    def test_build_codex_command_uses_resume_only_for_same_role_mode(self) -> None:
        fresh = build_codex_command(
            workdir="C:/repo",
            prompt_file="C:/repo/.omx/prompts/run.md",
            output_file="C:/repo/.omx/last.txt",
            resume_mode="fresh",
            model="gpt-5.4",
            profile=None,
            yolo=True,
        )
        resumed = build_codex_command(
            workdir="C:/repo",
            prompt_file="C:/repo/.omx/prompts/run.md",
            output_file="C:/repo/.omx/last.txt",
            resume_mode="resume_same_role",
            model="gpt-5.4",
            profile=None,
            yolo=True,
        )
        self.assertNotIn("resume", fresh)
        self.assertIn("resume", resumed)

    def test_run_codex_command_forces_utf8_stdin_encoding(self) -> None:
        with patch("scripts.research_agent_cli.subprocess.run") as run_mock:
            run_codex_command(
                ["codex", "exec", "-"],
                cwd=Path("C:/repo"),
                prompt_text="中文 prompt with unicode",
            )
        _, kwargs = run_mock.call_args
        self.assertTrue(kwargs["text"])
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["input"], "中文 prompt with unicode")

    def test_prompt_hash_uses_same_run_state_basis_as_autoloop(self) -> None:
        run_state = {
            "phase": "runner",
            "current_objective": "obj",
            "agent_program_ref": "ref",
            "runner_iteration": 1,
            "reader_iteration": 2,
            "next_action": "watch",
        }
        hash_from_autoloop_basis = compute_prompt_contract_hash("person-a", "agent-a", "runner", run_state)
        hash_from_agent_cli_basis = compute_prompt_contract_hash("person-a", "agent-a", "runner", run_state)
        self.assertEqual(hash_from_autoloop_basis, hash_from_agent_cli_basis)

    def test_consume_pending_human_prompt_if_matched_only_clears_matching_prompt(self) -> None:
        run_state = {
            "phase": "runner",
            "pending_human_prompt": {
                "target": "runner",
                "text": "runner only",
                "created_at": "2026-04-14T00:00:00Z",
            },
        }
        untouched = consume_pending_human_prompt_if_matched(run_state, matched_prompt=None)
        self.assertIn("pending_human_prompt", untouched)
        consumed = consume_pending_human_prompt_if_matched(run_state, matched_prompt={"target": "runner", "text": "runner only"})
        self.assertNotIn("pending_human_prompt", consumed)

    def test_compact_summary_renders_hash_and_excerpt(self) -> None:
        summary = compact_text_summary("person_program", Path("person_program.md"), "Core Objective test text " * 10, max_excerpt=20)
        rendered = render_compact_summary(summary)
        self.assertIn("sha256=", rendered)
        self.assertNotIn("excerpt=", rendered)

    def test_person_program_corruption_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "person_program.md"
            path.write_text("# person_program.md\n\n## 1. ????\n## 2. ????\n## 3. ????\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_validated_text(path, "person_program")

    def test_person_program_allows_human_freeform_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "person_program.md"
            path.write_text(
                "# person_program.md\n\n## My current mission\nThis document is human-authored and may evolve over time.\nIt explains the paper direction, the evidence priorities, and the practical constraints for the loop.\n\n## What matters now\nPrior-family uncertainty matters more than preserving one older metric story.\n",
                encoding="utf-8",
            )
            text = read_validated_text(path, "person_program")
            self.assertIn("human-authored", text)

    def test_agent_program_mixed_content_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent_program.md"
            path.write_text("# agent_program.md\n\n## Current Strategy\n- Reader keeps current strategy.\n\n## Revision Suggestions\n- None yet.\n", encoding="utf-8")
            text = read_validated_text(path, "agent_program")
            self.assertIn("Current Strategy", text)

    def test_agent_program_is_soft_constraint_no_rejection(self) -> None:
        # agent_program.md is a soft-constraint artifact — no strict validation.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent_program.md"
            path.write_text("# agent_program.md\n\n## Current Strategy\n- ???\n", encoding="utf-8")
            text = read_validated_text(path, "agent_program")
            self.assertIn("???", text)

    def test_supervisor_template_uses_launch_bash_helper(self) -> None:
        template = build_supervisor_template(
            Path("."),
            300,
            {"remote": {
                "ssh_key": "key",
                "host": "host",
                "port": 22,
                "remote_code_dir": "/remote/code",
                "remote_result_dir": "/remote/results",
            }},
        )
        self.assertIn("launch-bash", template)
        self.assertIn("--script-file <local-bash-script>", template)

    def test_write_launch_metadata_records_prompt_hash_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_path = write_launch_metadata(
                root,
                role="runner",
                rendered_prompt_hash="rendered-hash",
                prompt_file=root / "prompt.md",
                command_file=root / "command.txt",
                report_file=root / "report.md",
            )
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["rendered_prompt_hash"], "rendered-hash")

    def test_repo_agent_program_has_no_legacy_omx_report_or_synced_result_refs(self) -> None:
        text = Path("agent_program.md").read_text(encoding="utf-8")
        self.assertNotIn(".omx/reports", text)
        self.assertNotIn(".omx/reports/", text)
        self.assertNotIn(".omx/synced-results", text)
        self.assertNotIn(".omx/synced-results/", text)


if __name__ == "__main__":
    unittest.main()
