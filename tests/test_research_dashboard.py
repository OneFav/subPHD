from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

from scripts import research_dashboard


class ResearchDashboardTests(unittest.TestCase):

    def test_observatory_data_files_exist_and_parse(self) -> None:
        for rel in ["files/data/plan.json", "files/data/agents.json", "files/data/glossary.json"]:
            with self.subTest(rel=rel):
                payload = json.loads((Path(rel)).read_text(encoding="utf-8-sig"))
                self.assertIsNotNone(payload)

    def test_dashboard_server_serves_observatory_index_and_data_files(self) -> None:
        server = research_dashboard.create_dashboard_server("127.0.0.1", 0, port_search_limit=1)
        research_dashboard.DashboardHandler.root = Path.cwd()
        import threading
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            index = urllib.request.urlopen(base + "/", timeout=5).read().decode("utf-8")
            self.assertIn("The <em>subPHD</em> Observatory", index)
            self.assertIn("Plan &amp; Progress", index)
            self.assertIn("fetch('/api/prompt'", index)
            with urllib.request.urlopen(base + "/data/plan.json", timeout=5) as response:
                self.assertIn("application/json", response.headers.get("Content-Type", ""))
                json.loads(response.read().decode("utf-8-sig"))
        finally:
            server.shutdown()
            server.server_close()


    def test_queue_one_time_prompt_writes_pending_human_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ["person_program.md", "agent_program.md"]:
                (root / name).write_text(Path(name).read_text(encoding="utf-8"), encoding="utf-8")
            updated = research_dashboard.queue_one_time_prompt(
                root,
                target="next_actual_agent",
                text="Use the Observatory JSON contract.",
            )
            self.assertEqual(updated["pending_human_prompt"]["target"], "next_actual_agent")
            self.assertIn("Observatory JSON", updated["pending_human_prompt"]["text"])

    def test_observatory_prompt_contract_is_in_agent_prompt_source(self) -> None:
        source = Path("scripts/research_agent_cli.py").read_text(encoding="utf-8")
        self.assertIn("Observatory dashboard data maintenance", source)
        self.assertIn("files/data/plan.json", source)
        self.assertIn("files/data/agents.json", source)
        self.assertIn("files/data/glossary.json", source)
        self.assertIn("Do not stream or expose full internal chain-of-thought", source)

    def test_build_dashboard_html_contains_prompt_panel_theme_toggle_and_sub_phd_title(self) -> None:
        html = research_dashboard.build_dashboard_html(
            rows=[{
                "role": "runner",
                "task": "Investigate regression",
                "started_at": "2026-04-14T00:00:00Z",
                "elapsed_seconds": 120,
                "eta": "2026-04-14T00:10:00Z",
                "expected_output": "root-cause note",
                "why": "stabilize the loop",
                "status": "running",
            }],
            pending_prompt={"target": "runner", "text": "Focus on logs first."},
            last_launch_metadata={"applied_prompt_target": "runner", "prompt_consumed": False},
        )
        self.assertIn("sub-PHD", html)
        self.assertIn("Next Agent Prompt", html)
        self.assertIn("textarea", html)
        self.assertIn("next_actual_agent", html)
        self.assertIn("theme-toggle", html)
        self.assertIn("subphd-theme", html)
        self.assertIn("Signal", html)
        self.assertIn("Editorial", html)
        self.assertNotIn("lang-toggle", html)
        self.assertIn("Current iteration", html)
        self.assertIn("Run time", html)

    def test_build_dashboard_html_contains_summary_strip_and_compact_list_layout(self) -> None:
        html = research_dashboard.build_dashboard_html(
            rows=[{
                "role": "reader",
                "task": "Review benchmark drift",
                "started_at": "2026-04-14T00:00:00Z",
                "ended_at": "2026-04-14T00:35:00Z",
                "eta": "2026-04-14T00:30:00Z",
                "expected_output": "decision memo",
                "why": "choose next lane",
                "status": "running",
            }],
            pending_prompt={"target": "reader", "text": "Start with summary."},
            last_launch_metadata={"applied_role": "runner"},
        )
        self.assertIn("summary-strip", html)
        self.assertIn("timeline-list", html)
        self.assertIn("timeline-item", html)
        self.assertIn("task-primary", html)
        self.assertNotIn("segment-track", html)
        self.assertNotIn("segment-track-fill", html)
        self.assertNotIn("hero-copy", html)
        self.assertNotIn("timeline-status", html)
        self.assertIn(".timeline-main {", html)
        self.assertIn("width: 100%;", html)
        self.assertIn("grid-template-columns: repeat(4, minmax(108px, auto));", html)
        self.assertIn("04-14T08:00", html)
        self.assertIn("04-14T08:35", html)

    def test_build_dashboard_html_keeps_task_first_visual_priority(self) -> None:
        html = research_dashboard.build_dashboard_html(
            rows=[{
                "role": "runner",
                "task": "Stabilize prompt hash resume path",
                "started_at": "2026-04-14T00:00:00Z",
                "ended_at": "",
                "eta": "2026-04-14T00:12:00Z",
                "expected_output": "resume-safe launch metadata",
                "why": "prevent prompt loss after consumption",
                "status": "running",
            }],
            pending_prompt=None,
            last_launch_metadata=None,
        )
        self.assertIn("task-primary", html)
        self.assertIn("Stabilize prompt hash resume path", html)
        self.assertIn("meta-inline", html)
        self.assertIn("detail-grid", html)
        self.assertIn("detail-block", html)
        self.assertIn("Expected", html)
        self.assertIn("Why", html)
        self.assertIn("current-focus", html)

    def test_dashboard_timestamp_formats_to_beijing_time(self) -> None:
        self.assertEqual(
            research_dashboard._format_dashboard_timestamp("2026-04-14T06:38:00Z"),
            "04-14T14:38",
        )

    def test_build_dashboard_html_places_most_recent_task_lower_in_list(self) -> None:
        html = research_dashboard.build_dashboard_html(
            rows=[
                {
                    "role": "reader",
                    "task": "Older task",
                    "started_at": "2026-04-14T00:00:00Z",
                    "ended_at": "",
                    "eta": "2026-04-14T00:20:00Z",
                    "expected_output": "older output",
                    "why": "older why",
                    "status": "running",
                },
                {
                    "role": "runner",
                    "task": "Newest task",
                    "started_at": "2026-04-14T01:00:00Z",
                    "ended_at": "",
                    "eta": "2026-04-14T01:20:00Z",
                    "expected_output": "new output",
                    "why": "new why",
                    "status": "running",
                },
            ],
            pending_prompt=None,
            last_launch_metadata=None,
        )
        self.assertLess(html.index("Older task"), html.rindex("Newest task"))

    def test_build_gantt_rows_keeps_required_fields(self) -> None:
        rows = research_dashboard.build_gantt_rows({
            "segments": [{
                "role": "reader",
                "task": "Review the latest results",
                "started_at": "2026-04-14T00:00:00Z",
                "ended_at": None,
                "eta": "2026-04-14T00:05:00Z",
                "expected_output": "next-step plan",
                "why": "decide handoff",
                "status": "running",
            }]
        })
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["role"], "reader")
        self.assertEqual(rows[0]["expected_output"], "next-step plan")

    def test_dashboard_script_help_runs_from_repo_root(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/research_dashboard.py", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("sub-PHD dashboard", completed.stdout)

    def test_create_dashboard_server_falls_back_when_preferred_port_is_busy(self) -> None:
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        busy_port = blocker.getsockname()[1]
        server = None
        try:
            server = research_dashboard.create_dashboard_server("127.0.0.1", busy_port, port_search_limit=5)
            self.assertNotEqual(server.server_address[1], busy_port)
        finally:
            if server is not None:
                server.server_close()
            blocker.close()


if __name__ == "__main__":
    unittest.main()
