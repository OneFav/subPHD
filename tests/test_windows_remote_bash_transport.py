from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.research_supervisor import RemoteConfig, run_remote_bash_script


class WindowsRemoteBashTransportTests(unittest.TestCase):
    def test_run_remote_bash_script_sends_binary_lf_payload(self) -> None:
        captured = {}

        class Result:
            returncode = 0
            stdout = 'ok'
            stderr = ''

        def fake_run(cmd, input=None, capture_output=None, text=None, timeout=None):
            captured['cmd'] = cmd
            captured['input'] = input
            captured['text'] = text
            return Result()

        with patch('scripts.research_supervisor.subprocess.run', side_effect=fake_run):
            out = run_remote_bash_script(
                config=RemoteConfig(ssh_key='key', host='host', port=22),
                remote_workdir='/remote/code',
                script_text='echo one\necho two\n',
                timeout=30,
            )

        self.assertEqual(out, 'ok')
        self.assertIsInstance(captured['input'], bytes)
        self.assertEqual(captured['text'], False)
        self.assertNotIn(b'\r\n', captured['input'])
        self.assertIn(b'cd /remote/code\n', captured['input'])


if __name__ == '__main__':
    unittest.main()
