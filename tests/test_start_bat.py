from __future__ import annotations

import unittest
from pathlib import Path


class StartBatTests(unittest.TestCase):
    def test_start_bat_uses_auto_port_keeps_failures_visible_and_resets_fresh_state(self) -> None:
        script = Path("start.bat").read_text(encoding="utf-8")
        self.assertIn('set "HOURS=8"', script)
        self.assertIn("research_dashboard.py --workdir", script)
        self.assertIn("--port 0", script)
        self.assertIn("AUTOLOOP_RC", script)
        self.assertIn("pause >nul", script)
        self.assertIn("ROOT:~-1", script)
        self.assertIn("reset_runtime_state", script)
        self.assertIn("--ignore-state", script)

    def test_resume_bat_uses_auto_port_without_forcing_fresh_reset(self) -> None:
        script = Path("resume.bat").read_text(encoding="utf-8")
        self.assertIn('set "HOURS=8"', script)
        self.assertIn("research_dashboard.py --workdir", script)
        self.assertIn("--port 0", script)
        self.assertIn("AUTOLOOP_RC", script)
        self.assertIn("pause >nul", script)
        self.assertIn("ROOT:~-1", script)
        self.assertNotIn("reset_runtime_state", script)
        self.assertNotIn("--ignore-state", script)


if __name__ == "__main__":
    unittest.main()
