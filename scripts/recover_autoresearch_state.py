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
    default_run_state,
    load_loop_state,
    load_run_state,
    now_utc_iso,
)


def sync_loop_state_with_run_state(paths, run_state: dict[str, Any], reason: str) -> dict[str, Any]:
    loop_state = load_loop_state(paths.loop_state)
    phase = run_state.get("phase")
    if phase == "reader":
        loop_state["next_agent"] = "reader"
    elif phase == "runner":
        loop_state["next_agent"] = "runner"
    else:
        loop_state["next_agent"] = "runner"
    loop_state["last_transition_reason"] = reason
    loop_state["updated_at"] = now_utc_iso()
    atomic_write_json(paths.loop_state, loop_state)
    return loop_state


def load_or_repair_run_state(paths, config: dict[str, Any], reason: str) -> dict[str, Any]:
    try:
        return load_run_state(paths.run_state)
    except Exception as exc:
        repaired = default_run_state(config)
        repaired["repair_count"] = 1
        repaired["last_error"] = f"{reason}: {exc}"
        repaired["last_result_summary"] = f"Auto-repaired malformed run-state during recovery: {exc}"
        repaired["updated_at"] = now_utc_iso()
        atomic_write_json(paths.run_state, repaired)
        sync_loop_state_with_run_state(paths, repaired, "recover_repaired_run_state")
        return repaired


def write_run_state(paths, run_state: dict[str, Any], reason: str) -> None:
    run_state["updated_at"] = now_utc_iso()
    atomic_write_json(paths.run_state, run_state)
    sync_loop_state_with_run_state(paths, run_state, reason)


def reset_to_reader(paths, reason: str = "manual_reset_to_reader") -> dict[str, Any]:
    run_state = load_run_state(paths.run_state)
    previous_phase = run_state.get("phase")
    previous_run_id = run_state.get("run_id")
    run_state["phase"] = "reader"
    run_state["run_id"] = None
    run_state["remote_status"] = "idle"
    run_state["next_action"] = "reader"
    run_state["runner_iteration"] = 0
    run_state["last_error"] = None
    run_state["last_result_summary"] = (
        f"State reset to reader from phase={previous_phase}, run_id={previous_run_id}, reason={reason}."
    )
    write_run_state(paths, run_state, reason)
    return run_state


def resume_from_current_state(root: Path, config: dict[str, Any], paths) -> dict[str, Any]:
    run_state = load_or_repair_run_state(paths, config, "resume_from_current_state")
    if run_state.get("phase") != "watch":
        sync_loop_state_with_run_state(paths, run_state, "recover_resume_no_phase_change")
        return run_state

    run_id = run_state.get("run_id")
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
    updated = advance_run_state_after_watch(run_state, snapshot)
    write_run_state(paths, updated, "recover_resume_watch")
    return updated


def inspect_current_state(root: Path, config: dict[str, Any], paths, remote_check: bool = False) -> dict[str, Any]:
    run_state = load_or_repair_run_state(paths, config, "inspect_current_state")
    payload: dict[str, Any] = {"run_state": run_state}
    if remote_check and run_state.get("phase") == "watch":
        remote = config.get("remote", {}) if isinstance(config, dict) else {}
        payload["remote_poll"] = research_supervisor.poll_remote(
            config=research_supervisor.RemoteConfig(
                ssh_key=remote.get("ssh_key", ""),
                host=remote.get("host", ""),
                port=int(remote.get("port", 22)),
            ),
            screen_prefixes=[run_state.get("run_id")] if run_state.get("run_id") else [],
            result_dir=remote.get("remote_result_dir", ""),
            assignment_id="run-state",
            run_id=run_state.get("run_id"),
            snapshot_path=paths.watch_snapshot,
            event_log_path=paths.watch_events,
            timeout=90,
        )
    if run_state.get("phase") == "reader":
        payload["recommended_action"] = "resume_autoloop_or_launch_reader"
    elif run_state.get("phase") == "runner":
        payload["recommended_action"] = "resume_autoloop_or_launch_runner"
    else:
        payload["recommended_action"] = "resume_recovery_or_autoloop_watch"
    return payload


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Inspect, resume, or safely reset simplified research runtime state.")
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
