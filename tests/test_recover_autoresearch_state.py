from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.research_agent_cli import load_project_config
from scripts.research_loop_contract import bootstrap_state_artifacts, load_task_state, atomic_write_json
import scripts.recover_autoresearch_state as recover


class RecoverAutoresearchStateTests(unittest.TestCase):
    def write_config(self, root: Path) -> None:
        (root / 'research_agent.toml').write_text(
            '''default_hours = 1
default_max_runs = 5
default_poll_seconds = 5

[remote]
ssh_key = "key"
host = "host"
port = 22
remote_code_dir = "/remote/code"
remote_result_dir = "/remote/results"
gpu_count = 1

[artifacts]
person_program = "person_program.md"
agent_program = "agent_program.md"
loop_state = ".omx/state/research_loop_state.json"
watch_snapshot = ".omx/state/research_watch_snapshot.json"
watch_events = ".omx/state/research_watch_events.jsonl"
run_state = ".omx/state/run-state.json"
ai_worklog = ".omx/logs/ai-worklog.md"
''',
            encoding='utf-8',
        )

    def seed_programs(self, root: Path) -> None:
        (root / 'person_program.md').write_text(
            '# person_program.md\n\n## 1. Core Objective for This Cycle\nTest recovery.\n\n## 2. Default Priority Order\nKeep things simple.\n\n## 3. Reader Responsibilities\nReader decides next step.\n\nTest body text long enough to pass validation.\n',
            encoding='utf-8',
        )
        (root / 'agent_program.md').write_text(
            '# agent_program.md\n\n## Current Strategy\n- Recover cleanly.\n\n## Revision Suggestions\n- None yet.\n',
            encoding='utf-8',
        )

    def make_paths(self, tmp: str):
        root = Path(tmp)
        self.write_config(root)
        self.seed_programs(root)
        config = load_project_config(root)
        return root, config, bootstrap_state_artifacts(root, config)

    def test_reset_to_reader_clears_remote_execution_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, config, paths = self.make_paths(tmp)
            run_state = load_task_state(paths.task_state)
            run_state.update({
                'phase': 'watch',
                'run_id': 'R1',
                'remote_status': 'running',
                'runner_iteration': 1,
                'runner_iteration_cap': 2,
                'next_action': 'watch',
                'last_error': 'old error',
            })
            atomic_write_json(paths.task_state, run_state)

            recover.reset_to_reader(paths, reason='manual_reset')

            final_state = load_task_state(paths.task_state)
            self.assertEqual(final_state['phase'], 'reader')
            self.assertIsNone(final_state['run_id'])
            self.assertEqual(final_state['remote_status'], 'idle')
            self.assertEqual(final_state['next_action'], 'reader')
            self.assertIsNone(final_state['last_error'])
            task_state_check = load_task_state(paths.task_state)
            self.assertEqual(task_state_check['window_role'], 'reader')

    def test_resume_watch_advances_to_reader_when_synced_and_runner_cap_reached(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, config, paths = self.make_paths(tmp)
            run_state = load_task_state(paths.task_state)
            run_state.update({
                'phase': 'watch',
                'run_id': 'R1',
                'remote_status': 'submitted',
                'runner_iteration': 1,
                'runner_iteration_cap': 1,
                'next_action': 'watch',
            })
            atomic_write_json(paths.task_state, run_state)

            snapshot = {
                'watch_status': 'synced',
                'local_evidence_paths': {'result.json': 'C:/repo/result.json'},
                'failure_reason': None,
            }
            with patch('scripts.recover_autoresearch_state.research_supervisor.poll_remote', return_value=snapshot):
                updated = recover.resume_from_current_state(root, config, paths)

            self.assertEqual(updated['phase'], 'reader')
            self.assertEqual(updated['remote_status'], 'synced')
            self.assertIn('result.json', updated['last_result_summary'])

    def test_resume_watch_failed_poll_returns_runner_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, config, paths = self.make_paths(tmp)
            run_state = load_task_state(paths.task_state)
            run_state.update({
                'phase': 'watch',
                'run_id': 'R1',
                'remote_status': 'submitted',
                'runner_iteration': 1,
                'runner_iteration_cap': 3,
                'next_action': 'watch',
                'repair_count': 0,
            })
            atomic_write_json(paths.task_state, run_state)

            snapshot = {
                'watch_status': 'failed',
                'local_evidence_paths': None,
                'failure_reason': 'remote timeout',
            }
            with patch('scripts.recover_autoresearch_state.research_supervisor.poll_remote', return_value=snapshot):
                updated = recover.resume_from_current_state(root, config, paths)

            self.assertEqual(updated['phase'], 'runner')
            self.assertEqual(updated['next_action'], 'self_repair_and_retry')
            self.assertEqual(updated['repair_count'], 1)
            self.assertEqual(updated['last_error'], 'remote timeout')


if __name__ == '__main__':
    unittest.main()
