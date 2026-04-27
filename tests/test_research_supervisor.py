from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.research_supervisor import (
    LocalRunConfig,
    aggregate_result_summaries,
    build_remote_bash_argv,
    build_experiment_log_block,
    build_watch_snapshot,
    build_parser,
    cli_launch_bash,
    is_process_active,
    launch_local_bash_file,
    parse_screen_ls,
    poll_local,
    run_remote_bash_script,
    watch_local,
    write_watch_artifacts,
)
from scripts.research_loop_contract import validate_watch_snapshot


class ResearchSupervisorTests(unittest.TestCase):
    def test_parse_screen_ls_extracts_names(self) -> None:
        output = """There are screens on:
\t575.r4_tuned_s7\t(04/08/26 13:49:44)\t(Detached)
\t576.r4_tuned_s13\t(04/08/26 13:49:44)\t(Detached)
2 Sockets in /run/screen/S-root.
"""
        self.assertEqual(parse_screen_ls(output), ["r4_tuned_s7", "r4_tuned_s13"])

    def test_aggregate_result_summaries_averages_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload1 = {
                "summary": {
                    "current": {
                        "success_rate": 0.1,
                        "hits_at_budget_mean": 1.0,
                        "auc_found_targets_mean": 10.0,
                        "time_to_first_hit_mean": 100.0,
                    },
                    "candidate": {
                        "success_rate": 0.2,
                        "hits_at_budget_mean": 2.0,
                        "auc_found_targets_mean": 20.0,
                        "time_to_first_hit_mean": 200.0,
                    },
                }
            }
            payload2 = {
                "summary": {
                    "current": {
                        "success_rate": 0.3,
                        "hits_at_budget_mean": 3.0,
                        "auc_found_targets_mean": 30.0,
                        "time_to_first_hit_mean": 300.0,
                    },
                    "candidate": {
                        "success_rate": 0.4,
                        "hits_at_budget_mean": 4.0,
                        "auc_found_targets_mean": 40.0,
                        "time_to_first_hit_mean": 400.0,
                    },
                }
            }
            (root / "a.json").write_text(json.dumps(payload1), encoding="utf-8")
            (root / "b.json").write_text(json.dumps(payload2), encoding="utf-8")
            agg = aggregate_result_summaries([root / "a.json", root / "b.json"])
            self.assertAlmostEqual(agg["current"]["success_rate"], 0.2)
            self.assertAlmostEqual(agg["candidate"]["auc_found_targets_mean"], 30.0)

    def test_build_experiment_log_block_contains_required_fields(self) -> None:
        summary = {
            "candidate": {
                "success_rate": 0.4,
                "hits_at_budget_mean": 1.5,
                "auc_found_targets_mean": 123.4,
                "time_to_first_hit_mean": 111.0,
            }
        }
        block = build_experiment_log_block(
            iteration=3,
            title="Supervisor summary",
            hypothesis="candidate should win",
            patch_summary="added supervisor",
            smoke_result="ok",
            full_run_result="done",
            primary_metric_delta="hits +0.5",
            guardrail_status="ok",
            keep_or_revert="keep",
            why="candidate wins",
            next_best_step="run more",
            aggregate_summary=summary,
        )
        self.assertIn("ITERATION 3", block)
        self.assertIn("### ITERATION 3 — Supervisor summary", block)
        self.assertIn("candidate", block)

    def test_build_watch_snapshot_contains_local_evidence_paths(self) -> None:
        snapshot = build_watch_snapshot(
            assignment_id="A1",
            run_id="R1",
            watch_status="synced",
            runner_active=False,
            supervisor_polling=False,
            remote_screen_names=[],
            remote_jsons=["remote.json"],
            local_evidence_paths={"remote.json": "C:/repo/remote.json"},
            failure_reason=None,
        )
        self.assertEqual(snapshot["local_evidence_paths"]["remote.json"], "C:/repo/remote.json")

    def test_malformed_local_evidence_paths_fail_closed(self) -> None:
        snapshot = build_watch_snapshot(
            assignment_id="A1",
            run_id="R1",
            watch_status="synced",
            runner_active=False,
            supervisor_polling=False,
            remote_screen_names=[],
            remote_jsons=["remote.json"],
            local_evidence_paths={"remote.json": "ssh://remote/path"},
            failure_reason=None,
        )
        with self.assertRaises(ValueError):
            validate_watch_snapshot(snapshot)

    def test_missing_assignment_id_fails_closed(self) -> None:
        snapshot = build_watch_snapshot(
            assignment_id="A1",
            run_id="R1",
            watch_status="synced",
            runner_active=False,
            supervisor_polling=False,
            remote_screen_names=[],
            remote_jsons=["remote.json"],
            local_evidence_paths={"remote.json": "C:/repo/remote.json"},
            failure_reason=None,
        )
        snapshot.pop("assignment_id")
        with self.assertRaises(ValueError):
            validate_watch_snapshot(snapshot)

    def test_write_watch_artifacts_appends_event_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot_path = root / "snapshot.json"
            event_log_path = root / "events.jsonl"
            snapshot = build_watch_snapshot(
                assignment_id="A1",
                run_id="R1",
                watch_status="running",
                runner_active=True,
                supervisor_polling=True,
                remote_screen_names=["R1"],
                remote_jsons=[],
                local_evidence_paths=None,
                failure_reason=None,
            )
            write_watch_artifacts(
                snapshot_path=snapshot_path,
                event_log_path=event_log_path,
                snapshot=snapshot,
                assignment_id="A1",
                run_id="R1",
                event_type="poll",
                reason="remote_poll",
                source="supervisor",
            )
            self.assertTrue(snapshot_path.exists())
            lines = event_log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["assignment_id"], "A1")
            self.assertEqual(payload["run_id"], "R1")

    def test_build_remote_bash_argv_is_structured(self) -> None:
        from scripts.research_supervisor import RemoteConfig

        argv = build_remote_bash_argv(RemoteConfig(ssh_key="key", host="host", port=22))
        self.assertEqual(argv[-2:], ["bash", "-s"])
        self.assertNotIn("@'", " ".join(argv))

    def test_run_remote_bash_script_uses_stdin_payload_not_here_string(self) -> None:
        from unittest.mock import patch
        from scripts.research_supervisor import RemoteConfig

        captured = {}

        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def fake_run(cmd, input=None, capture_output=None, text=None, timeout=None):
            captured["cmd"] = cmd
            captured["input"] = input
            captured["text"] = text
            return Result()

        with patch("scripts.research_supervisor.subprocess.run", side_effect=fake_run):
            out = run_remote_bash_script(
                config=RemoteConfig(ssh_key="key", host="host", port=22),
                remote_workdir="/remote/code",
                script_text="python foo.py --bar\n",
                timeout=30,
            )

        self.assertEqual(out, "ok")
        self.assertEqual(captured["cmd"][-2:], ["bash", "-s"])
        self.assertIsInstance(captured["input"], bytes)
        self.assertEqual(captured["text"], False)
        self.assertIn(b"cd /remote/code", captured["input"])
        self.assertNotIn(b"@'", captured["input"])

    def test_launch_bash_subcommand_uses_canonical_transport(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script_file = root / "run.sh"
            script_file.write_text("python foo.py --bar\n", encoding="utf-8")
            captured = {}

            def fake_run_remote_bash_file(*, config, remote_workdir, script_file, timeout=300):
                captured["config"] = config
                captured["remote_workdir"] = remote_workdir
                captured["script_file"] = script_file
                captured["timeout"] = timeout
                return "ok"

            parser = build_parser()
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
            self.assertEqual(Path(captured["script_file"]), script_file)

    def test_run_remote_bash_script_failure_is_compactly_truncated(self) -> None:
        from unittest.mock import patch
        from scripts.research_supervisor import RemoteConfig

        class Result:
            returncode = 1
            stdout = "A" * 1200
            stderr = "B" * 1200

        with patch("scripts.research_supervisor.subprocess.run", return_value=Result()):
            with self.assertRaises(RuntimeError) as ctx:
                run_remote_bash_script(
                    config=RemoteConfig(ssh_key="key", host="host", port=22),
                    remote_workdir="/remote/code",
                    script_text="python foo.py --bar\n",
                    timeout=30,
                )

        msg = str(ctx.exception)
        self.assertIn("STDOUT_SNIPPET", msg)
        self.assertIn("STDERR_SNIPPET", msg)
        self.assertLess(len(msg), 1200)

    def test_launch_local_bash_file_creates_metadata_and_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "run.py"
            script.write_text(
                "from pathlib import Path\n"
                "Path('results').mkdir(exist_ok=True)\n"
                "Path('results/summary.json').write_text('{\"ok\": true}', encoding='utf-8')\n",
                encoding="utf-8",
            )
            launcher = root / "launch.ps1"
            launcher.write_text(f"python {script.name}\n", encoding="utf-8")
            config = LocalRunConfig(
                workdir=root,
                result_dir=root / "results",
                log_dir=root / ".omx" / "logs" / "local-runs",
                pid_dir=root / ".omx" / "state" / "local-runs",
            )
            metadata = launch_local_bash_file(
                config=config,
                script_file=launcher,
                run_id="local-test-run",
            )
            self.assertEqual(metadata["backend"], "local")
            self.assertEqual(metadata["run_id"], "local-test-run")
            self.assertTrue(Path(metadata["metadata_path"]).exists())
            self.assertTrue(Path(metadata["log_path"]).exists())
            for _ in range(30):
                if not is_process_active(int(metadata["pid"])):
                    break
                time.sleep(0.1)

    def test_poll_local_reports_synced_when_process_finished_with_json_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_dir = root / "results"
            result_dir.mkdir()
            (result_dir / "summary.json").write_text('{"ok": true}', encoding="utf-8")
            metadata_path = root / ".omx" / "state" / "local-runs" / "local-done.json"
            metadata_path.parent.mkdir(parents=True)
            metadata_path.write_text(json.dumps({
                "backend": "local",
                "run_id": "local-done",
                "pid": 0,
                "returncode": 0,
                "command": "python done.py",
                "workdir": str(root),
                "log_path": str(root / "done.log"),
                "result_dir": str(result_dir),
                "started_at": "2026-04-27T00:00:00Z",
                "ended_at": "2026-04-27T00:00:01Z",
            }), encoding="utf-8")
            snapshot = poll_local(
                metadata_path=metadata_path,
                result_dir=result_dir,
                assignment_id="A1",
                run_id="local-done",
                local_glob="*.json",
            )
            self.assertEqual(snapshot["backend"], "local")
            self.assertEqual(snapshot["watch_status"], "synced")
            self.assertFalse(snapshot["runner_active"])
            self.assertIn("summary.json", snapshot["local_evidence_paths"])

    def test_poll_local_reports_failed_when_exit_code_is_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_dir = root / "results"
            result_dir.mkdir()
            metadata_path = root / ".omx" / "state" / "local-runs" / "local-failed.json"
            metadata_path.parent.mkdir(parents=True)
            metadata_path.write_text(json.dumps({
                "backend": "local",
                "run_id": "local-failed",
                "pid": 0,
                "returncode": 7,
                "command": "python fail.py",
                "workdir": str(root),
                "log_path": str(root / "failed.log"),
                "result_dir": str(result_dir),
                "started_at": "2026-04-27T00:00:00Z",
                "ended_at": "2026-04-27T00:00:01Z",
            }), encoding="utf-8")
            snapshot = poll_local(
                metadata_path=metadata_path,
                result_dir=result_dir,
                assignment_id="A1",
                run_id="local-failed",
                local_glob="*.json",
            )
            self.assertEqual(snapshot["watch_status"], "failed")
            self.assertEqual(snapshot["failure_reason"], "local_process_exit_7")

    def test_watch_local_returns_running_for_active_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_path = root / ".omx" / "state" / "local-runs" / "local-running.json"
            metadata_path.parent.mkdir(parents=True)
            metadata_path.write_text(json.dumps({
                "backend": "local",
                "run_id": "local-running",
                "pid": 999999,
                "returncode": None,
                "command": "python sleep.py",
                "workdir": str(root),
                "log_path": str(root / "running.log"),
                "result_dir": str(root / "results"),
                "started_at": "2026-04-27T00:00:00Z",
            }), encoding="utf-8")
            with patch("scripts.research_supervisor.is_process_active", return_value=True), \
                 patch("scripts.research_supervisor.time.sleep", return_value=None):
                snapshot = watch_local(
                    metadata_path=metadata_path,
                    result_dir=root / "results",
                    poll_seconds=1,
                    snapshot_path=None,
                    event_log_path=None,
                    max_polls=1,
                    assignment_id="A1",
                    run_id="local-running",
                    local_glob="*.json",
                )
            self.assertEqual(snapshot["backend"], "local")
            self.assertEqual(snapshot["watch_status"], "running")
            self.assertTrue(snapshot["runner_active"])


if __name__ == "__main__":
    unittest.main()
