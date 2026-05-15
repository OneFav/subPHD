from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.build_migration_pack import PACK_NAME, SCRIPT_FILES, build_migration_pack
from scripts.research_agent_cli import load_project_config
from scripts.research_loop_contract import load_task_state, read_json, read_validated_text


class BuildMigrationPackTests(unittest.TestCase):
    def test_build_migration_pack_creates_fresh_template_with_preserved_ssh_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir(parents=True, exist_ok=True)
            (root / "scripts").mkdir(parents=True, exist_ok=True)
            for name in SCRIPT_FILES:
                (root / "scripts" / name).write_text("# placeholder\n", encoding="utf-8")
            (root / "research_agent.toml").write_text(
                """
project_name = "demo"
default_model = "gpt-5.4"
default_hours = 10
default_max_runs = 30
default_poll_seconds = 300

[remote]
ssh_key = "C:/keys/id_ed25519"
host = "root@example.com"
port = 22222
remote_code_dir = "/remote/code/demo"
remote_result_dir = "/remote/code/demo/results"
gpu_count = 4

[logs]
results_jsonl = "research/results.jsonl"
experiment_log_md = "research/EXPERIMENT_LOG.md"
claims_md = "research/CLAIMS.md"
memory_md = "research/MEMORY.md"
next_experiment_md = "research/NEXT_EXPERIMENT.md"

[artifacts]
person_program = "person_program.md"
agent_program = "agent_program.md"
loop_state = ".omx/state/research_loop_state.json"
watch_snapshot = ".omx/state/research_watch_snapshot.json"
watch_events = ".omx/state/research_watch_events.jsonl"
run_state = ".omx/state/run-state.json"
ai_worklog = ".omx/logs/ai-worklog.md"
agent_observability = ".omx/state/agent-observability.json"

[loop]
slow_heartbeat_seconds = 300
gpu_count = 4
""".strip(),
                encoding="utf-8",
            )
            output_dir = root / "dist"
            pack_root, zip_path = build_migration_pack(root, output_dir)

            self.assertEqual(pack_root.name, PACK_NAME)
            self.assertTrue(zip_path.exists())
            config = load_project_config(pack_root)
            self.assertEqual(config["remote"]["ssh_key"], "C:/keys/id_ed25519")
            self.assertEqual(config["remote"]["host"], "root@example.com")
            self.assertEqual(config["remote"]["port"], 22222)
            self.assertEqual(config["runtime"]["root"], ".subphd")
            task_state = load_task_state(pack_root / ".subphd" / "state" / "task-state.json")
            self.assertEqual(task_state["phase"], "reader")
            self.assertEqual(task_state["next_action"], "reader")
            person_program = read_validated_text(pack_root / "person_program.md", "person_program")
            self.assertIn("only required human-authored control document", person_program)
            agent_program = read_validated_text(pack_root / "agent_program.md", "agent_program")
            self.assertIn("Current Strategy", agent_program)
            self.assertTrue((pack_root / "roles" / "reader" / "AGENTS.md").exists())
            self.assertTrue((pack_root / "roles" / "runner" / "skills" / "runner-implementation" / "SKILL.md").exists())
            self.assertTrue((pack_root / "roles" / "reader" / "skills" / "experiment-plan" / "SKILL.md").exists())
            self.assertTrue((pack_root / "roles" / "reader" / "skills" / "analyze-results" / "SKILL.md").exists())
            self.assertTrue((pack_root / "roles" / "reader" / "skills" / "result-to-claim" / "SKILL.md").exists())
            self.assertTrue((pack_root / "roles" / "runner" / "skills" / "experiment-bridge" / "SKILL.md").exists())
            self.assertTrue((pack_root / "roles" / "runner" / "skills" / "monitor-experiment" / "SKILL.md").exists())
            self.assertTrue((pack_root / "roles" / "runner" / "skills" / "training-check" / "SKILL.md").exists())
            self.assertFalse((pack_root / "workspaces").exists())
            self.assertTrue((pack_root / "README-migrate.md").exists())
            self.assertTrue((pack_root / "README.md").exists())
            self.assertTrue((pack_root / "README.zh-CN.md").exists())
            self.assertTrue((pack_root / "start.bat").exists())
            self.assertTrue((pack_root / "resume.bat").exists())
            self.assertIn('set "HOURS=1"', (pack_root / "start.bat").read_text(encoding="utf-8"))
            self.assertIn('set "HOURS=1"', (pack_root / "resume.bat").read_text(encoding="utf-8"))
            migrate_readme = (pack_root / "README-migrate.md").read_text(encoding="utf-8")
            self.assertIn("role-local", migrate_readme.lower())
            self.assertIn("authoritative handoff", migrate_readme.lower())


if __name__ == "__main__":
    unittest.main()
