from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import research_autoloop
from scripts.research_agent_cli import build_supervisor_template, load_project_config
from scripts.research_supervisor import build_parser as build_supervisor_parser, cli_launch_bash
from scripts.research_loop_contract import bootstrap_state_artifacts, read_json


class ResearchLoopIntegrationTests(unittest.TestCase):
    def write_config(self, root: Path) -> None:
        (root / "research_agent.toml").write_text(
            """
default_hours = 10
default_max_runs = 30
default_poll_seconds = 1

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

[loop]
slow_heartbeat_seconds = 1
""".strip(),
            encoding="utf-8",
        )

    def test_autoloop_main_drives_three_cycles_with_real_watch_remote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(root)
            (root / "person_program.md").write_text(
                "# person_program.md\n\n## 1. Core Objective for This Cycle\nBuild the strongest paper evidence package.\n\n## 2. Default Priority Order\nFirst mainline evidence.\n\n## 3. Reader Responsibilities\nThe reader defines the next step.\n\nThis paper direction needs the best evidence package.\n",
                encoding="utf-8",
            )
            config = load_project_config(root)
            paths = bootstrap_state_artifacts(root, config)

            call_roles: list[tuple[str, str]] = []
            run_state_path = paths.task_state
            reader_counter = {"value": 0}
            runner_counter = {"value": 0}
            poll_counter = {"value": 0}

            def fake_subprocess_run(cmd, cwd=None, **kwargs):
                role = cmd[cmd.index("--role") + 1]
                resume_mode = cmd[cmd.index("--resume-mode") + 1]
                call_roles.append((role, resume_mode))
                run_state = json.loads(run_state_path.read_text(encoding="utf-8"))
                if role == "reader":
                    reader_counter["value"] += 1
                    run_state["reader_iteration"] = reader_counter["value"]
                    run_state["current_objective"] = f"objective-{reader_counter['value']}"
                    run_state["success_condition"] = "remote sync completes"
                    run_state["phase"] = "runner"
                    run_state["next_action"] = "runner"
                    run_state["remote_status"] = "idle"
                    run_state["run_id"] = None
                else:
                    runner_counter["value"] += 1
                    run_state["runner_iteration"] = runner_counter["value"]
                    run_state["run_id"] = f"R{runner_counter['value']}"
                    run_state["phase"] = "watch"
                    run_state["next_action"] = "watch"
                    run_state["remote_status"] = "submitted"
                run_state_path.write_text(json.dumps(run_state, ensure_ascii=False, indent=2), encoding="utf-8")

                class Result:
                    returncode = 0

                return Result()

            def fake_ssh_output(config, remote_command, timeout=60):
                run_state = json.loads(run_state_path.read_text(encoding="utf-8")) if run_state_path.exists() else None
                run_id = run_state.get("run_id") if run_state else None
                if "screen -ls" in remote_command:
                    poll_counter["value"] += 1
                    if poll_counter["value"] == 1:
                        return f"There are screens on:\n\t1.{run_id}\t(Detached)\n1 Sockets in /run/screen/S-root.\n"
                    return "No Sockets found.\n"
                if "nvidia-smi" in remote_command:
                    return "0, 1000 MiB, 20 %\n"
                if "ls -1" in remote_command:
                    if poll_counter["value"] == 1:
                        return "remote.json\n"
                    return "/remote/results/remote.json\n"
                return ""

            def fake_scp_fetch(config, remote_path, local_path, timeout=120):
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_text('{"summary": {}}', encoding="utf-8")

            with patch("scripts.research_autoloop.subprocess.run", side_effect=fake_subprocess_run), \
                 patch("scripts.research_supervisor.ssh_output", side_effect=fake_ssh_output), \
                 patch("scripts.research_supervisor.scp_fetch", side_effect=fake_scp_fetch), \
                 patch("scripts.research_autoloop.time.sleep", return_value=None), \
                 patch("scripts.research_supervisor.time.sleep", return_value=None), \
                 patch("sys.argv", ["research_autoloop.py", "--workdir", str(root), "--hours", "0.1", "--max-runs", "11", "--ignore-state"]):
                rc = research_autoloop.main()

            self.assertEqual(rc, 0)
            self.assertGreaterEqual(reader_counter["value"], 2)
            self.assertGreaterEqual(runner_counter["value"], 2)
            self.assertTrue(all(resume_mode in {"fresh", "resume_same_role"} for _, resume_mode in call_roles))
            self.assertEqual(call_roles[0][1], "fresh")
            final_state = read_json(paths.task_state)
            self.assertGreaterEqual(final_state["reader_iteration"], 2)
            self.assertGreaterEqual(final_state["runner_iteration"], 1)
            self.assertIn("window_role", final_state)
            snapshot = read_json(paths.watch_snapshot)
            self.assertEqual(snapshot["watch_status"], "synced")
            self.assertIsNotNone(snapshot["local_evidence_paths"])
            events = paths.watch_events.read_text(encoding="utf-8").strip().splitlines()
            self.assertGreaterEqual(len(events), 3)

    def test_launch_bash_transport_path_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(root)
            script_file = root / "launch.sh"
            script_file.write_text("python foo.py --bar\n", encoding="utf-8")
            config = load_project_config(root)
            template = build_supervisor_template(root, 300, config)
            self.assertIn("launch-bash", template)

            captured = {}

            def fake_run_remote_bash_file(*, config, remote_workdir, script_file, timeout=300):
                captured["remote_workdir"] = remote_workdir
                captured["script_file"] = str(script_file)
                captured["timeout"] = timeout
                return "ok"

            parser = build_supervisor_parser()
            args = parser.parse_args([
                "launch-bash",
                "--ssh-key", "key",
                "--host", "host",
                "--port", "22",
                "--remote-workdir", "/remote/code",
                "--script-file", str(script_file),
            ])

            with patch("scripts.research_supervisor.run_remote_bash_file", side_effect=fake_run_remote_bash_file):
                rc = cli_launch_bash(args)

            self.assertEqual(rc, 0)
            self.assertEqual(captured["remote_workdir"], "/remote/code")
            self.assertEqual(captured["script_file"], str(script_file))


if __name__ == "__main__":
    unittest.main()
