#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import argparse
import json
import subprocess
import time
from typing import Any

from scripts import research_supervisor
from scripts.research_agent_cli import load_project_config
from scripts.research_loop_contract import (
    RUN_PHASE_VALUES,
    append_jsonl,
    atomic_write_json,
    bootstrap_state_artifacts,
    compute_prompt_contract_hash,
    compute_resume_key,
    evaluate_success_condition,
    load_task_state,
    now_utc_iso,
    read_validated_text,
    reset_runtime_state,
    resolve_execution_backend,
    text_sha256,
)



def build_loop_command(
    *,
    workdir: str,
    role: str,
    resume_mode: str,
    model: str,
    expected_prompt_contract_hash: str,
    no_yolo: bool,
) -> list[str]:
    cmd = [
        "python",
        "scripts/research_agent_cli.py",
        "--workdir",
        workdir,
        "--role",
        role,
        "--resume-mode",
        resume_mode,
        "--model",
        model,
        "--expected-prompt-contract-hash",
        expected_prompt_contract_hash,
    ]
    if no_yolo:
        cmd.append("--no-yolo")
    return cmd


def update_task_state(paths, task_state: dict[str, Any]) -> None:
    from scripts.research_loop_contract import atomic_write_json
    task_state["updated_at"] = now_utc_iso()
    atomic_write_json(paths.task_state, task_state)


def should_resume(task_state: dict[str, Any], role: str, agent_program_hash: str) -> tuple[str, bool]:
    """返回 (resume_mode, start_new_window)"""
    window_role = task_state.get("window_role")
    stored_key = task_state.get("resume_key")
    has_new_human = bool(task_state.get("applied_human_prompt"))
    current_key = compute_resume_key(role, task_state, agent_program_hash, has_new_human)
    resume_count = int(task_state.get("resume_count", 0))
    resume_budget = int(task_state.get("resume_budget", 3))

    if stored_key is None or window_role != role:
        return "fresh", True
    if stored_key == current_key and resume_count < resume_budget:
        return "resume_same_role", False
    return "fresh", True


def advance_run_state_after_watch(run_state: dict[str, Any], snapshot: dict[str, Any], repair_cap: int = 3) -> dict[str, Any]:
    next_state = dict(run_state)
    status = snapshot.get("watch_status", "missing")
    backend = snapshot.get("backend") or next_state.get("execution_backend")
    if backend:
        next_state["execution_backend"] = backend
    next_state["remote_status"] = status
    local_evidence = snapshot.get("local_evidence_paths") or {}
    if local_evidence:
        next_state["last_result_summary"] = ", ".join(sorted(local_evidence.keys()))
    if status == "synced":
        next_state["last_error"] = None
        next_state["runner_iteration"] = int(next_state.get("runner_iteration", 0)) + 1
        if int(next_state.get("runner_iteration", 0)) >= int(next_state.get("runner_iteration_cap", 0)):
            next_state["phase"] = "reader"
            next_state["next_action"] = "reader"
            next_state["runner_done_reason"] = "cap_exhausted"
        else:
            next_state["phase"] = "runner"
            next_state["next_action"] = "runner"
        return next_state
    if status in {"failed", "timed_out", "missing"}:
        next_state["repair_count"] = int(next_state.get("repair_count", 0)) + 1
        next_state["last_error"] = snapshot.get("failure_reason") or status
        next_state["no_improvement_count"] = int(next_state.get("no_improvement_count", 0)) + 1
        if int(next_state.get("repair_count", 0)) >= repair_cap:
            next_state["phase"] = "reader"
            next_state["next_action"] = "reader"
            next_state["runner_done_reason"] = "repair_cap_exhausted"
        else:
            next_state["phase"] = "runner"
            next_state["next_action"] = "self_repair_and_retry"
        return next_state
    # running, submitted, results_ready, idle — keep watching
    next_state["phase"] = "watch"
    next_state["next_action"] = "watch"
    return next_state


def _resolve_config_path(root: Path, value: str | None, default: str) -> Path:
    raw = value or default
    path = Path(raw)
    return path if path.is_absolute() else root / path


def launch_role(
    *,
    root: Path,
    config: dict[str, Any],
    paths,
    task_state: dict[str, Any],
    role: str,
    resume_mode: str,
    model: str,
    no_yolo: bool,
    loop_log: Path,
    run_index: int,
    dry_run: bool,
) -> int:
    person_program = read_validated_text(paths.person_program, "person_program")
    agent_program = read_validated_text(paths.agent_program, "agent_program")
    prompt_hash = compute_prompt_contract_hash(
        person_program, agent_program, role, task_state
    )
    launch_metadata_path = paths.last_launch_metadata
    cmd = build_loop_command(
        workdir=str(root),
        role=role,
        resume_mode=resume_mode,
        model=model,
        expected_prompt_contract_hash=prompt_hash,
        no_yolo=no_yolo,
    )
    append_jsonl(loop_log, {
        "time": int(time.time()),
        "event": "launch",
        "run_index": run_index,
        "role": role,
        "resume_mode": resume_mode,
        "cmd_summary": {
            "program": cmd[0],
            "script": cmd[1] if len(cmd) > 1 else None,
            "role": role,
            "resume_mode": resume_mode,
            "model": model,
            "prompt_contract_hash": prompt_hash,
        },
        "launch_metadata_path": str(launch_metadata_path),
        "canonical_transport_marker": (
            "scripts/research_supervisor.py launch --backend local"
            if resolve_execution_backend(config) == "local"
            else "scripts/research_supervisor.py launch-bash"
        ),
    })
    print(f"[autoloop] run {run_index}: role={role} resume={resume_mode} model={model} hash={prompt_hash}")
    if dry_run:
        return 0
    completed = subprocess.run(cmd, cwd=root)
    metadata_payload = None
    if launch_metadata_path.exists():
        try:
            metadata_payload = json.loads(launch_metadata_path.read_text(encoding="utf-8"))
        except Exception:
            metadata_payload = None
    append_jsonl(loop_log, {
        "time": int(time.time()),
        "event": "completed",
        "run_index": run_index,
        "role": role,
        "returncode": int(completed.returncode),
        "launch_metadata": metadata_payload,
    })
    return int(completed.returncode)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="sub-PHD runtime autoloop with explicit reader/runner routing.")
    ap.add_argument("--workdir", default=".")
    ap.add_argument("--hours", type=float, default=10.0)
    ap.add_argument("--max-runs", type=int, default=50)
    ap.add_argument("--model", default="gpt-5.4")
    ap.add_argument("--sleep-seconds", type=int, default=15)
    ap.add_argument("--ignore-state", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-yolo", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.workdir).resolve()
    config = load_project_config(root)
    paths = bootstrap_state_artifacts(root, config)
    if args.ignore_state:
        reset_runtime_state(paths, config, reason="ignore_state_fresh_start")
    deadline = time.time() + args.hours * 3600.0
    loop_dir = paths.autoloop_root
    loop_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    loop_log = loop_dir / f"research-autoloop-{stamp}.jsonl"
    loop_cfg = config.get("loop", {}) if isinstance(config, dict) else {}
    slow_heartbeat = int(loop_cfg.get("slow_heartbeat_seconds", config.get("default_poll_seconds", 300)))
    repair_cap = int(loop_cfg.get("repair_cap", 3))
    local_result_dir = paths.synced_results_root
    run_index = 0

    TERMINAL_PHASES = {"done", "abandoned", "needs_human"}

    while run_index < args.max_runs and time.time() < deadline:
        task_state = load_task_state(paths.task_state)
        phase = task_state["phase"]

        # --- Terminal state check ---
        # "done" means the *current sprint* completed, not the whole session.
        # If budget remains, auto-advance to reader for the next sprint.
        if phase == "done":
            if run_index + 1 < args.max_runs and time.time() < deadline:
                task_state["phase"] = "reader"
                task_state["next_action"] = "reader"
                task_state["sprint_contract"] = None
                task_state["runner_iteration"] = 0
                task_state["repair_count"] = 0
                task_state["no_improvement_count"] = 0
                task_state["last_error"] = None
                task_state["runner_done_reason"] = None
                task_state["run_id"] = None
                task_state["remote_status"] = "idle"
                task_state["updated_at"] = now_utc_iso()
                atomic_write_json(paths.task_state, task_state)
                append_jsonl(loop_log, {"time": int(time.time()), "event": "auto_advance", "reason": "sprint_done_budget_remaining"})
                print("[autoloop] Sprint done — advancing to next sprint (reader).")
                continue
            else:
                append_jsonl(loop_log, {"time": int(time.time()), "event": "stop", "reason": "terminal_phase_done_no_budget"})
                print("Stopping: done and no budget remaining.")
                return 0
        if phase in {"abandoned", "needs_human"}:
            append_jsonl(loop_log, {"time": int(time.time()), "event": "stop", "reason": f"terminal_phase_{phase}"})
            print(f"Stopping: terminal phase {phase}.")
            return 0


        # --- Promote pending human prompt at safe point ---
        pending = task_state.get("pending_human_prompt")
        if isinstance(pending, dict) and pending.get("text"):
            task_state["applied_human_prompt"] = dict(pending)
            task_state.pop("pending_human_prompt", None)
            task_state["updated_at"] = now_utc_iso()
            atomic_write_json(paths.task_state, task_state)

        run_index += 1

        # --- Reader phase ---
        if phase == "reader":
            person_program = read_validated_text(paths.person_program, "person_program")
            agent_program = read_validated_text(paths.agent_program, "agent_program")
            prompt_hash = compute_prompt_contract_hash(
                person_program, agent_program, "reader", task_state
            )
            agent_hash = text_sha256(agent_program)
            resume_mode, new_window = should_resume(task_state, "reader", agent_hash)
            task_state["resume_key"] = compute_resume_key("reader", task_state, agent_hash, bool(task_state.get("applied_human_prompt")))
            if new_window:
                task_state["window_role"] = "reader"
                task_state["resume_count"] = 0
            else:
                task_state["resume_count"] = int(task_state.get("resume_count", 0)) + 1
            task_state["prompt_contract_hash"] = prompt_hash
            task_state["updated_at"] = now_utc_iso()
            atomic_write_json(paths.task_state, task_state)

            launch_role(
                root=root, config=config, paths=paths, task_state=task_state,
                role="reader", resume_mode=resume_mode, model=args.model,
                no_yolo=args.no_yolo, loop_log=loop_log, run_index=run_index,
                dry_run=args.dry_run,
            )
            if time.time() < deadline and run_index < args.max_runs:
                time.sleep(max(1, args.sleep_seconds))
            continue

        # --- Runner phase ---
        if phase == "runner":
            person_program = read_validated_text(paths.person_program, "person_program")
            agent_program = read_validated_text(paths.agent_program, "agent_program")
            prompt_hash = compute_prompt_contract_hash(
                person_program, agent_program, "runner", task_state
            )
            agent_hash = text_sha256(agent_program)
            resume_mode, new_window = should_resume(task_state, "runner", agent_hash)
            task_state["resume_key"] = compute_resume_key("runner", task_state, agent_hash, bool(task_state.get("applied_human_prompt")))
            if new_window:
                task_state["window_role"] = "runner"
                task_state["resume_count"] = 0
            else:
                task_state["resume_count"] = int(task_state.get("resume_count", 0)) + 1
            task_state["prompt_contract_hash"] = prompt_hash
            task_state["updated_at"] = now_utc_iso()
            atomic_write_json(paths.task_state, task_state)

            launch_role(
                root=root, config=config, paths=paths, task_state=task_state,
                role="runner", resume_mode=resume_mode, model=args.model,
                no_yolo=args.no_yolo, loop_log=loop_log, run_index=run_index,
                dry_run=args.dry_run,
            )

            # After runner completes, re-read state to see what runner wants
            try:
                post_state = load_task_state(paths.task_state)
            except Exception:
                post_state = task_state
            post_phase = post_state.get("phase")

            # If runner set terminal phase, stop on next iteration
            if post_phase in TERMINAL_PHASES:
                continue

            # If runner set watch, sleep and let next iteration handle it
            if post_phase == "watch":
                if time.time() < deadline and run_index < args.max_runs:
                    time.sleep(max(1, args.sleep_seconds))
                continue

            # If runner stayed runner (multi-round), minimal sleep, loop again
            if post_phase == "runner":
                if time.time() < deadline and run_index < args.max_runs:
                    time.sleep(max(1, args.sleep_seconds // 3))
                continue

            # Otherwise (reader phase), normal sleep
            if time.time() < deadline and run_index < args.max_runs:
                time.sleep(max(1, args.sleep_seconds))
            continue

        # --- Watch phase ---
        if phase == "watch":
            backend = task_state.get("execution_backend") or resolve_execution_backend(config)
            if backend == "local":
                local_cfg = config.get("local", {}) if isinstance(config, dict) else {}
                local_pid_dir = _resolve_config_path(root, local_cfg.get("pid_dir"), ".omx/state/local-runs")
                local_result_path = _resolve_config_path(root, local_cfg.get("result_dir"), "results")
                run_id = task_state.get("run_id")
                metadata_path = local_pid_dir / f"{run_id}.json" if run_id else local_pid_dir / "latest.json"
                snapshot = research_supervisor.watch_local(
                    metadata_path=metadata_path, result_dir=local_result_path,
                    poll_seconds=slow_heartbeat, snapshot_path=paths.watch_snapshot,
                    event_log_path=paths.watch_events, max_polls=1,
                    assignment_id="run-state", run_id=run_id, local_glob="*.json",
                )
            else:
                remote_cfg = config.get("remote", {}) if isinstance(config, dict) else {}
                snapshot = research_supervisor.watch_remote(
                    config=research_supervisor.RemoteConfig(
                        ssh_key=remote_cfg.get("ssh_key", ""),
                        host=remote_cfg.get("host", ""),
                        port=int(remote_cfg.get("port", 22)),
                    ),
                    screen_prefixes=[task_state["run_id"]] if task_state.get("run_id") else [],
                    remote_result_dir=remote_cfg.get("remote_result_dir", ""),
                    local_result_dir=local_result_dir, poll_seconds=slow_heartbeat,
                    snapshot_path=paths.watch_snapshot, event_log_path=paths.watch_events,
                    max_polls=1, assignment_id="run-state", run_id=task_state.get("run_id"),
                )
            task_state = advance_run_state_after_watch(task_state, snapshot, repair_cap=repair_cap)

            # --- After watch: evaluate sprint contract ---
            # Only finalize the sprint when runner cap is exhausted (phase=reader)
            # or when the sprint has been abandoned. While cap remains, runner
            # continues iterating even if artifacts already exist.
            post_phase = task_state.get("phase")
            sprint_contract = task_state.get("sprint_contract")
            if isinstance(sprint_contract, dict) and post_phase == "reader":
                sc = sprint_contract.get("success_condition")
                if isinstance(sc, dict):
                    satisfied, details = evaluate_success_condition(sc, task_state)
                    if satisfied:
                        task_state["phase"] = "done"
                        task_state["next_action"] = "done"
                        task_state["runner_done_reason"] = f"success_condition_satisfied: {details}"
                        task_state["updated_at"] = now_utc_iso()
                        update_task_state(paths, task_state)
                        append_jsonl(loop_log, {"time": int(time.time()), "event": "sprint_success", "reason": "success_condition_satisfied", "details": details})
                        print(f"[autoloop] Sprint success (cap {task_state.get('runner_iteration')}/{task_state.get('runner_iteration_cap')}) — {details}")
                        continue

                # Cap exhausted, success not met — check failure_policy
                fp = sprint_contract.get("failure_policy") or {}
                no_imp_cap = int(fp.get("no_improvement_cap", 0))
                if no_imp_cap > 0 and int(task_state.get("no_improvement_count", 0)) >= no_imp_cap:
                    task_state["phase"] = "abandoned"
                    task_state["next_action"] = "abandoned"
                    task_state["runner_done_reason"] = "no_improvement_cap_exhausted"
                    task_state["updated_at"] = now_utc_iso()
                    update_task_state(paths, task_state)
                    append_jsonl(loop_log, {"time": int(time.time()), "event": "sprint_abandoned", "reason": "no_improvement_cap_exhausted"})
                    print("[autoloop] Sprint abandoned: no improvement cap exhausted.")
                    continue

            update_task_state(paths, task_state)
            append_jsonl(loop_log, {
                "time": int(time.time()), "event": "watch_phase_transition",
                "run_index": run_index, "watch_status": snapshot.get("watch_status"),
                "next_phase": task_state.get("phase"),
            })
            continue

        raise ValueError(f"invalid phase: {phase!r}")

    reason = "deadline" if time.time() >= deadline else "max_runs"
    append_jsonl(loop_log, {"time": int(time.time()), "event": "stop", "reason": reason})
    print(f"Stopping: {reason}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
