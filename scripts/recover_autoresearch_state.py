#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import research_supervisor
from scripts.research_agent_cli import load_project_config
from scripts.research_autoloop import advance_run_state_after_watch
from scripts.research_loop_contract import (
    atomic_write_json,
    bootstrap_state_artifacts,
    default_task_state,
    load_task_state,
    now_utc_iso,
    resolve_execution_backend,
)


def load_or_repair_task_state(paths, config: dict[str, Any], reason: str) -> dict[str, Any]:
    try:
        return load_task_state(paths.task_state)
    except Exception as exc:
        repaired = default_task_state(config)
        repaired["repair_count"] = 1
        repaired["last_error"] = f"{reason}: {exc}"
        repaired["last_result_summary"] = f"Auto-repaired malformed task-state during recovery: {exc}"
        repaired["updated_at"] = now_utc_iso()
        atomic_write_json(paths.task_state, repaired)
        return repaired


def write_task_state(paths, task_state: dict[str, Any], reason: str) -> None:
    task_state["updated_at"] = now_utc_iso()
    atomic_write_json(paths.task_state, task_state)


def reset_to_reader(paths, reason: str = "manual_reset_to_reader") -> dict[str, Any]:
    task_state = load_task_state(paths.task_state)
    previous_phase = task_state.get("phase")
    previous_run_id = task_state.get("run_id")
    task_state["phase"] = "reader"
    task_state["run_id"] = None
    task_state["remote_status"] = "idle"
    task_state["next_action"] = "reader"
    task_state["runner_iteration"] = 0
    task_state["last_error"] = None
    task_state["last_result_summary"] = (
        f"State reset to reader from phase={previous_phase}, run_id={previous_run_id}, reason={reason}."
    )
    write_task_state(paths, task_state, reason)
    return task_state


def resume_from_current_state(root: Path, config: dict[str, Any], paths) -> dict[str, Any]:
    task_state = load_or_repair_task_state(paths, config, "resume_from_current_state")
    if task_state.get("phase") != "watch":
        return task_state

    run_id = task_state.get("run_id")
    backend = resolve_execution_backend(config)

    if backend == "local":
        from scripts.research_supervisor import watch_local
        local_cfg = config.get("local", {}) if isinstance(config, dict) else {}
        local_pid_dir = Path(local_cfg.get("pid_dir", ".omx/state/local-runs"))
        if not local_pid_dir.is_absolute():
            local_pid_dir = root / local_pid_dir
        local_result_dir = Path(local_cfg.get("result_dir", "results"))
        if not local_result_dir.is_absolute():
            local_result_dir = root / local_result_dir
        metadata_path = local_pid_dir / f"{run_id}.json" if run_id else local_pid_dir / "latest.json"
        snapshot = watch_local(
            metadata_path=metadata_path,
            result_dir=local_result_dir,
            poll_seconds=90,
            snapshot_path=paths.watch_snapshot,
            event_log_path=paths.watch_events,
            max_polls=1,
            assignment_id="run-state",
            run_id=run_id,
            local_glob="*.json",
        )
    else:
        remote = config.get("remote", {}) if isinstance(config, dict) else {}
        snapshot = research_supervisor.poll_remote(
            config=research_supervisor.RemoteConfig(
                ssh_key=remote.get("ssh_key", ""),
                host=remote.get("host", ""),
                port=int(remote.get("port", 22)),
            ),
            screen_prefixes=[run_id] if run_id else [],
            result_dir=remote.get("remote_result_dir", ""),
            assignment_id="run-state",
            run_id=run_id,
            snapshot_path=paths.watch_snapshot,
            event_log_path=paths.watch_events,
            timeout=90,
        )

    updated = advance_run_state_after_watch(task_state, snapshot)
    write_task_state(paths, updated, "recover_resume_watch")
    return updated


def inspect_current_state(root: Path, config: dict[str, Any], paths, remote_check: bool = False) -> dict[str, Any]:
    task_state = load_or_repair_task_state(paths, config, "inspect_current_state")
    payload: dict[str, Any] = {"task_state": task_state}
    if remote_check and task_state.get("phase") == "watch":
        remote = config.get("remote", {}) if isinstance(config, dict) else {}
        payload["remote_poll"] = research_supervisor.poll_remote(
            config=research_supervisor.RemoteConfig(
                ssh_key=remote.get("ssh_key", ""),
                host=remote.get("host", ""),
                port=int(remote.get("port", 22)),
            ),
            screen_prefixes=[task_state.get("run_id")] if task_state.get("run_id") else [],
            result_dir=remote.get("remote_result_dir", ""),
            assignment_id="run-state",
            run_id=task_state.get("run_id"),
            snapshot_path=paths.watch_snapshot,
            event_log_path=paths.watch_events,
            timeout=90,
        )
    if task_state.get("phase") == "reader":
        payload["recommended_action"] = "resume_autoloop_or_launch_reader"
    elif task_state.get("phase") == "runner":
        payload["recommended_action"] = "resume_autoloop_or_launch_runner"
    else:
        payload["recommended_action"] = "resume_recovery_or_autoloop_watch"
    return payload


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Inspect, resume, or safely reset simplified autoresearch runtime state.")
    ap.add_argument("--workdir", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)

    inspect = sub.add_parser("inspect")
    inspect.add_argument("--remote-check", action="store_true")

    sub.add_parser("resume")

    reset = sub.add_parser("reset-to-reader")
    reset.add_argument("--reason", default="manual_reset_to_reader")

    return ap


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.workdir).resolve()
    config = load_project_config(root)
    paths = bootstrap_state_artifacts(root, config)

    if args.cmd == "inspect":
        payload = inspect_current_state(root, config, paths, remote_check=args.remote_check)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "resume":
        payload = resume_from_current_state(root, config, paths)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "reset-to-reader":
        payload = reset_to_reader(paths, reason=args.reason)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    raise ValueError(f"unknown cmd: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
