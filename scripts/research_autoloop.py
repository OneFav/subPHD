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
    authoritative_handoffs_root,
    atomic_write_json,
    build_authoritative_handoff_path,
    bootstrap_state_artifacts,
    compute_rendered_prompt_contract_hash,
    load_authoritative_handoff_payload,
    load_loop_state,
    load_run_state,
    now_utc_iso,
    new_role_window_id,
    read_validated_text,
    reset_runtime_state,
    resolve_execution_backend,
    stable_json,
    text_sha256,
)


def is_ralph_complete(root: Path) -> bool:
    candidates = [
        root / ".subphd" / "state" / "ralph-state.json",
        root / ".subphd" / "state" / "sessions",
    ]
    direct = candidates[0]
    if direct.exists():
        try:
            data = json.loads(direct.read_text(encoding="utf-8"))
            if data.get("active") is False or data.get("current_phase") == "complete":
                return True
        except Exception:
            pass

    sessions_dir = candidates[1]
    if sessions_dir.exists():
        state_files = sorted(sessions_dir.glob("*/ralph-state.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for state_file in state_files[:3]:
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                if data.get("active") is False or data.get("current_phase") == "complete":
                    return True
            except Exception:
                continue
    return False


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


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


def update_loop_state(paths, loop_state: dict[str, Any]) -> None:
    from scripts.research_loop_contract import atomic_write_json
    loop_state["updated_at"] = now_utc_iso()
    atomic_write_json(paths.loop_state, loop_state)


def update_run_state(paths, run_state: dict[str, Any]) -> None:
    from scripts.research_loop_contract import atomic_write_json
    run_state["updated_at"] = now_utc_iso()
    atomic_write_json(paths.run_state, run_state)


def choose_continuation_policy(*, loop_state: dict[str, Any], role: str, prompt_contract_hash: str, handoff_status: str = "valid") -> dict[str, Any]:
    budget = int(loop_state.get("resume_budget", 3))
    count = int(loop_state.get("resume_count", 0))
    window_role = loop_state.get("window_role")
    if loop_state.get("last_prompt_role") is None:
        return {
            "resume_mode": "fresh",
            "start_new_window": False,
            "next_window_role": role,
            "next_resume_count": 0,
            "generate_handoff": False,
            "rollover_reason": None,
        }
    if window_role != role:
        return {
            "resume_mode": "fresh",
            "start_new_window": True,
            "next_window_role": role,
            "next_resume_count": 0,
            "generate_handoff": False,
            "rollover_reason": None,
        }
    if (
        loop_state.get("last_prompt_role") == role
        and loop_state.get("prompt_contract_hash") == prompt_contract_hash
        and handoff_status == "valid"
        and count < budget
    ):
        return {
            "resume_mode": "resume_same_role",
            "start_new_window": False,
            "next_window_role": role,
            "next_resume_count": count + 1,
            "generate_handoff": False,
            "rollover_reason": None,
        }
    rollover_reason = "prompt_contract_changed"
    generate_handoff = False
    if count >= budget:
        rollover_reason = "resume_budget_exhausted"
        generate_handoff = True
    elif handoff_status != "valid":
        rollover_reason = "missing_or_invalid_authoritative_handoff"
    return {
        "resume_mode": "fresh",
        "start_new_window": True,
        "next_window_role": role,
        "next_resume_count": 0,
        "generate_handoff": generate_handoff,
        "rollover_reason": rollover_reason,
    }


def _build_authoritative_handoff_payload(paths, loop_state: dict[str, Any], run_state: dict[str, Any], role: str) -> dict[str, Any]:
    last_report_file = None
    if paths.last_launch_metadata.exists():
        try:
            metadata = json.loads(paths.last_launch_metadata.read_text(encoding="utf-8"))
            report_candidate = metadata.get("report_file")
            if isinstance(report_candidate, str) and report_candidate:
                last_report_file = Path(report_candidate)
        except Exception:
            last_report_file = None
    authoritative_artifacts: list[str] = [
        str(paths.person_program),
        str(paths.agent_program),
        str(paths.run_state),
    ]
    if last_report_file and last_report_file.exists():
        authoritative_artifacts.append(str(last_report_file))
    if paths.watch_snapshot.exists():
        try:
            snapshot = json.loads(paths.watch_snapshot.read_text(encoding="utf-8"))
            local_evidence = snapshot.get("local_evidence_paths") or {}
            if isinstance(local_evidence, dict):
                authoritative_artifacts.extend(str(value) for value in local_evidence.values() if isinstance(value, str) and value)
        except Exception:
            pass
    ordered_artifacts: list[str] = []
    seen: set[str] = set()
    for item in authoritative_artifacts:
        if item not in seen:
            ordered_artifacts.append(item)
            seen.add(item)
    current_objective = str(run_state.get("current_objective") or "")
    current_conclusions = str(run_state.get("last_result_summary") or "No current result summary recorded.")
    next_action = str(run_state.get("next_action") or role)
    payload = {
        "schema_version": 1,
        "big_round_id": loop_state.get("big_round_id"),
        "role_window_id": loop_state.get("role_window_id"),
        "window_role": loop_state.get("window_role"),
        "source_role": role,
        "generated_at": now_utc_iso(),
        "current_objective": current_objective,
        "current_conclusions": current_conclusions,
        "next_step_recommendation": f"Continue with the next planned action: {next_action}.",
        "authoritative_artifacts": ordered_artifacts,
        "key_evidence": [current_conclusions] if current_conclusions else [],
        "failed_or_do_not_repeat": [str(run_state.get('last_error'))] if run_state.get("last_error") else [],
        "open_uncertainties": [] if current_objective and current_conclusions else ["Current objective or conclusions are incomplete and need manual clarification."],
        "person_program_reader_judgment": f"`person_program.md` remains the human mission anchor for reader work; current objective is `{current_objective or 'unset'}`.",
        "agent_program_runner_judgment": f"`agent_program.md` remains the executable handoff for runner work; next action is `{next_action}`.",
        "planning_guidance": f"Use the authoritative handoff first, then authoritative artifacts, and only then generic recent reports if needed to complete `{next_action}`.",
        "handoff_summary_text": f"{role} window rollover after `{next_action}`. Objective: {current_objective or 'unset'}. Conclusions: {current_conclusions}",
    }
    payload["prompt_contract_basis_sha256"] = text_sha256(stable_json(payload))
    return payload


def _write_authoritative_handoff(paths, loop_state: dict[str, Any], run_state: dict[str, Any], role: str) -> tuple[Path, dict[str, Any]]:
    path = build_authoritative_handoff_path(paths, loop_state)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _build_authoritative_handoff_payload(paths, loop_state, run_state, role)
    atomic_write_json(path, payload)
    return path, payload


def resolve_authoritative_handoff(paths, loop_state: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    handoff_path_raw = loop_state.get("last_authoritative_handoff_path")
    if not isinstance(handoff_path_raw, str) or not handoff_path_raw:
        return None, "valid"
    try:
        payload = load_authoritative_handoff_payload(
            Path(handoff_path_raw),
            expected_big_round_id=loop_state.get("big_round_id"),
        )
        return payload, "valid"
    except Exception:
        return None, "invalid"


def advance_run_state_after_watch(run_state: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    next_state = dict(run_state)
    status = snapshot.get("watch_status", "missing")
    backend = snapshot.get("backend") or next_state.get("execution_backend")
    if backend:
        next_state["execution_backend"] = backend
    next_state["remote_status"] = status
    next_state["execution_status"] = status
    local_evidence = snapshot.get("local_evidence_paths") or {}
    if local_evidence:
        next_state["last_result_summary"] = ", ".join(sorted(local_evidence.keys()))
    if status == "synced":
        next_state["last_error"] = None
        if int(next_state.get("runner_iteration", 0)) >= int(next_state.get("runner_iteration_cap", 0)):
            next_state["phase"] = "reader"
            next_state["next_action"] = "reader"
        else:
            next_state["phase"] = "runner"
            next_state["next_action"] = "runner"
        return next_state
    if status in {"failed", "timed_out", "missing"}:
        next_state["phase"] = "runner"
        next_state["repair_count"] = int(next_state.get("repair_count", 0)) + 1
        next_state["last_error"] = snapshot.get("failure_reason") or status
        next_state["next_action"] = "self_repair_and_retry"
        return next_state
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
    loop_state: dict[str, Any],
    handoff_payload: dict[str, Any] | None,
    authoritative_handoff: dict[str, Any] | None,
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
    prompt_hash = compute_rendered_prompt_contract_hash(
        person_program,
        agent_program,
        role,
        handoff_payload,
        authoritative_handoff=authoritative_handoff,
    )
    loop_state["last_resume_mode"] = resume_mode
    update_loop_state(paths, loop_state)
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
    slow_heartbeat = int(config.get("loop", {}).get("slow_heartbeat_seconds", config.get("default_poll_seconds", 300)))
    local_result_dir = paths.synced_results_root
    run_index = 0

    while run_index < args.max_runs and time.time() < deadline:
        loop_state = load_loop_state(paths.loop_state)
        run_state = load_run_state(paths.run_state)
        phase = run_state["phase"]
        run_index += 1

        if phase == "reader":
            person_program = read_validated_text(paths.person_program, "person_program")
            agent_program = read_validated_text(paths.agent_program, "agent_program")
            authoritative_handoff, handoff_status = resolve_authoritative_handoff(paths, loop_state)
            prompt_hash = compute_rendered_prompt_contract_hash(
                person_program,
                agent_program,
                "reader",
                run_state,
                authoritative_handoff=authoritative_handoff,
            )
            policy = choose_continuation_policy(
                loop_state=loop_state,
                role="reader",
                prompt_contract_hash=prompt_hash,
                handoff_status=handoff_status,
            )
            if policy["generate_handoff"]:
                try:
                    handoff_path, authoritative_handoff = _write_authoritative_handoff(paths, loop_state, run_state, "reader")
                    loop_state["last_authoritative_handoff_path"] = str(handoff_path)
                    loop_state["last_rollover_at"] = now_utc_iso()
                    loop_state["last_rollover_reason"] = policy["rollover_reason"]
                    handoff_status = "valid"
                except Exception:
                    authoritative_handoff = None
                    handoff_status = "invalid"
                    policy["rollover_reason"] = "missing_or_invalid_authoritative_handoff"
            elif handoff_status != "valid":
                loop_state["last_authoritative_handoff_path"] = None
            if policy["start_new_window"]:
                loop_state["window_role"] = "reader"
                loop_state["role_window_id"] = new_role_window_id("reader")
                loop_state["resume_count"] = 0
            else:
                loop_state["resume_count"] = int(policy["next_resume_count"])
            loop_state["next_agent"] = "reader"
            loop_state["last_rollover_reason"] = policy["rollover_reason"]
            update_loop_state(paths, loop_state)
            launch_role(
                root=root,
                config=config,
                paths=paths,
                loop_state=loop_state,
                handoff_payload=run_state,
                authoritative_handoff=authoritative_handoff,
                role="reader",
                resume_mode=policy["resume_mode"],
                model=args.model,
                no_yolo=args.no_yolo,
                loop_log=loop_log,
                run_index=run_index,
                dry_run=args.dry_run,
            )
            if time.time() < deadline and run_index < args.max_runs:
                time.sleep(max(1, args.sleep_seconds))
            continue

        if phase == "runner":
            person_program = read_validated_text(paths.person_program, "person_program")
            agent_program = read_validated_text(paths.agent_program, "agent_program")
            authoritative_handoff, handoff_status = resolve_authoritative_handoff(paths, loop_state)
            prompt_hash = compute_rendered_prompt_contract_hash(
                person_program,
                agent_program,
                "runner",
                run_state,
                authoritative_handoff=authoritative_handoff,
            )
            policy = choose_continuation_policy(
                loop_state=loop_state,
                role="runner",
                prompt_contract_hash=prompt_hash,
                handoff_status=handoff_status,
            )
            if policy["generate_handoff"]:
                try:
                    handoff_path, authoritative_handoff = _write_authoritative_handoff(paths, loop_state, run_state, "runner")
                    loop_state["last_authoritative_handoff_path"] = str(handoff_path)
                    loop_state["last_rollover_at"] = now_utc_iso()
                    loop_state["last_rollover_reason"] = policy["rollover_reason"]
                    handoff_status = "valid"
                except Exception:
                    authoritative_handoff = None
                    handoff_status = "invalid"
                    policy["rollover_reason"] = "missing_or_invalid_authoritative_handoff"
            elif handoff_status != "valid":
                loop_state["last_authoritative_handoff_path"] = None
            if policy["start_new_window"]:
                loop_state["window_role"] = "runner"
                loop_state["role_window_id"] = new_role_window_id("runner")
                loop_state["resume_count"] = 0
            else:
                loop_state["resume_count"] = int(policy["next_resume_count"])
            loop_state["next_agent"] = "runner"
            loop_state["last_rollover_reason"] = policy["rollover_reason"]
            update_loop_state(paths, loop_state)
            launch_role(
                root=root,
                config=config,
                paths=paths,
                loop_state=loop_state,
                handoff_payload=run_state,
                authoritative_handoff=authoritative_handoff,
                role="runner",
                resume_mode=policy["resume_mode"],
                model=args.model,
                no_yolo=args.no_yolo,
                loop_log=loop_log,
                run_index=run_index,
                dry_run=args.dry_run,
            )
            if time.time() < deadline and run_index < args.max_runs:
                time.sleep(max(1, args.sleep_seconds))
            continue

        if phase not in RUN_PHASE_VALUES:
            raise ValueError(f"invalid phase: {phase}")

        backend = run_state.get("execution_backend") or resolve_execution_backend(config)
        if backend == "local":
            local_cfg = config.get("local", {}) if isinstance(config, dict) else {}
            local_pid_dir = _resolve_config_path(root, local_cfg.get("pid_dir"), ".omx/state/local-runs")
            local_result_path = _resolve_config_path(root, local_cfg.get("result_dir"), "results")
            run_id = run_state.get("run_id")
            metadata_path = local_pid_dir / f"{run_id}.json" if run_id else local_pid_dir / "latest.json"
            snapshot = research_supervisor.watch_local(
                metadata_path=metadata_path,
                result_dir=local_result_path,
                poll_seconds=slow_heartbeat,
                snapshot_path=paths.watch_snapshot,
                event_log_path=paths.watch_events,
                max_polls=1,
                assignment_id="run-state",
                run_id=run_id,
                local_glob="*.json",
            )
        else:
            snapshot = research_supervisor.watch_remote(
                config=research_supervisor.RemoteConfig(
                    ssh_key=config.get("remote", {}).get("ssh_key", ""),
                    host=config.get("remote", {}).get("host", ""),
                    port=int(config.get("remote", {}).get("port", 22)),
                ),
                screen_prefixes=[run_state["run_id"]] if run_state.get("run_id") else [],
                remote_result_dir=config.get("remote", {}).get("remote_result_dir", ""),
                local_result_dir=local_result_dir,
                poll_seconds=slow_heartbeat,
                snapshot_path=paths.watch_snapshot,
                event_log_path=paths.watch_events,
                max_polls=1,
                assignment_id="run-state",
                run_id=run_state.get("run_id"),
            )
        loop_state["last_watch_status"] = snapshot.get("watch_status")
        update_loop_state(paths, loop_state)
        run_state = advance_run_state_after_watch(run_state, snapshot)
        update_run_state(paths, run_state)
        append_jsonl(loop_log, {
            "time": int(time.time()),
            "event": "watch_phase_transition",
            "run_index": run_index,
            "watch_status": snapshot.get("watch_status"),
            "next_phase": run_state.get("phase"),
        })

    reason = "deadline" if time.time() >= deadline else "max_runs"
    append_jsonl(loop_log, {"time": int(time.time()), "event": "stop", "reason": reason})
    print(f"Stopping: {reason}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
