from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import unittest
import urllib.request
from pathlib import Path

from scripts import research_dashboard


class ResearchDashboardObservatoryTests(unittest.TestCase):
    def test_observatory_data_files_exist_and_parse(self) -> None:
        for rel in ["files/data/plan.json", "files/data/agents.json", "files/data/glossary.json"]:
            with self.subTest(rel=rel):
                payload = json.loads(Path(rel).read_text(encoding="utf-8-sig"))
                self.assertIsNotNone(payload)

    def test_dashboard_server_serves_observatory_index_and_data_files(self) -> None:
        server = research_dashboard.create_dashboard_server("127.0.0.1", 0, port_search_limit=1)
        research_dashboard.DashboardHandler.root = Path.cwd()
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
        import tempfile
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
