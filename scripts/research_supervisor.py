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
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Any

from scripts.research_loop_contract import SCHEMA_VERSION, append_jsonl as append_contract_jsonl, atomic_write_json, classify_watch_status, event_payload, now_utc_iso
from scripts.research_reporting import aggregate_result_summaries, append_jsonl, append_md, build_experiment_log_block


def parse_screen_ls(output: str) -> list[str]:
    names: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("There ") or line.startswith("No Sockets") or "Sockets in" in line:
            continue
        if "\t" in line and "." in line:
            first = line.split("\t", 1)[0]
            if "." in first:
                _, name = first.split(".", 1)
                names.append(name)
    return names

@dataclass
class RemoteConfig:
    ssh_key: str
    host: str
    port: int = 22


@dataclass
class LocalRunConfig:
    workdir: Path
    result_dir: Path
    log_dir: Path
    pid_dir: Path


_LOCAL_BACKGROUND_PROCESSES: list[subprocess.Popen[Any]] = []


def _remember_local_process(proc: subprocess.Popen[Any]) -> None:
    _LOCAL_BACKGROUND_PROCESSES[:] = [item for item in _LOCAL_BACKGROUND_PROCESSES if item.poll() is None]
    _LOCAL_BACKGROUND_PROCESSES.append(proc)


def _run(cmd: list[str], timeout: int = 60) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        stdout = (proc.stdout or "")[:400]
        stderr = (proc.stderr or "")[:400]
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"STDOUT_SNIPPET:\n{stdout}\nSTDERR_SNIPPET:\n{stderr}"
        )
    return proc.stdout


def ssh_output(config: RemoteConfig, remote_command: str, timeout: int = 60) -> str:
    cmd = [
        "ssh",
        "-i",
        config.ssh_key,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-p",
        str(config.port),
        config.host,
        remote_command,
    ]
    return _run(cmd, timeout=timeout)


def scp_fetch(config: RemoteConfig, remote_path: str, local_path: Path, timeout: int = 120) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "scp",
        "-i",
        config.ssh_key,
        "-P",
        str(config.port),
        f"{config.host}:{remote_path}",
        str(local_path),
    ]
    _run(cmd, timeout=timeout)


def build_remote_bash_argv(config: RemoteConfig) -> list[str]:
    return [
        "ssh",
        "-i",
        config.ssh_key,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-p",
        str(config.port),
        config.host,
        "bash",
        "-s",
    ]


def run_remote_bash_script(
    *,
    config: RemoteConfig,
    remote_workdir: str,
    script_text: str,
    timeout: int = 300,
) -> str:
    normalized_script = script_text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    payload = f"set -e\ncd {shlex.quote(remote_workdir)}\n{normalized_script}\n".encode("utf-8")
    cmd = build_remote_bash_argv(config)
    proc = subprocess.run(cmd, input=payload, capture_output=True, text=False, timeout=timeout)
    def _coerce_text(value: bytes | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    if proc.returncode != 0:
        stdout = _coerce_text(proc.stdout)[:300]
        stderr = _coerce_text(proc.stderr)[:300]
        raise RuntimeError(
            "Remote bash launch failed "
            f"({proc.returncode}): argv={cmd}\nSTDOUT_SNIPPET:\n{stdout}\nSTDERR_SNIPPET:\n{stderr}"
        )
    return _coerce_text(proc.stdout)


def run_remote_bash_file(
    *,
    config: RemoteConfig,
    remote_workdir: str,
    script_file: Path,
    timeout: int = 300,
) -> str:
    script_text = script_file.read_text(encoding="utf-8")
    return run_remote_bash_script(
        config=config,
        remote_workdir=remote_workdir,
        script_text=script_text,
        timeout=timeout,
    )


def is_process_active(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if sys.platform.startswith("win"):
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return str(pid) in (result.stdout or "")
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _local_metadata_path(config: LocalRunConfig, run_id: str) -> Path:
    return config.pid_dir / f"{run_id}.json"


def _local_result_paths(result_dir: Path, local_glob: str) -> dict[str, str]:
    if not result_dir.exists():
        return {}
    return {path.name: str(path) for path in sorted(result_dir.glob(local_glob)) if path.is_file()}


def _local_script_command(script_file: Path) -> list[str] | str:
    suffix = script_file.suffix.lower()
    if suffix == ".ps1":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_file)]
    if suffix in {".cmd", ".bat"}:
        return ["cmd", "/c", str(script_file)]
    if suffix == ".py":
        return [sys.executable, str(script_file)]
    if sys.platform.startswith("win"):
        return ["cmd", "/c", str(script_file)]
    return ["bash", str(script_file)]


def launch_local_bash_file(
    *,
    config: LocalRunConfig,
    script_file: Path,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or f"local-{time.strftime('%Y%m%dT%H%M%S')}"
    config.workdir.mkdir(parents=True, exist_ok=True)
    config.result_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    config.pid_dir.mkdir(parents=True, exist_ok=True)
    log_path = config.log_dir / f"{run_id}.log"
    metadata_path = _local_metadata_path(config, run_id)
    command = _local_script_command(script_file.resolve())
    log_path.touch()
    command_text = command if isinstance(command, str) else " ".join(command)
    wrapper_path = config.pid_dir / f"{run_id}-wrapper.py"
    wrapper_path.write_text(
        "\n".join([
            "import json, subprocess, sys",
            "from datetime import datetime, timezone",
            f"metadata_path = {str(metadata_path)!r}",
            f"log_path = {str(log_path)!r}",
            f"workdir = {str(config.workdir)!r}",
            f"command = {command!r}",
            "def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')",
            "returncode = 1",
            "try:",
            "    with open(log_path, 'ab') as log_handle:",
            "        proc = subprocess.run(command, cwd=workdir, stdout=log_handle, stderr=subprocess.STDOUT, shell=False)",
            "        returncode = int(proc.returncode)",
            "finally:",
            "    try:",
            "        with open(metadata_path, 'r', encoding='utf-8-sig') as f:",
            "            metadata = json.load(f)",
            "    except Exception:",
            "        metadata = {}",
            "    metadata['returncode'] = returncode",
            "    metadata['ended_at'] = now()",
            "    metadata['updated_at'] = now()",
            "    with open(metadata_path, 'w', encoding='utf-8') as f:",
            "        json.dump(metadata, f, ensure_ascii=False, indent=2)",
            "sys.exit(returncode)",
            "",
        ]),
        encoding="utf-8",
    )
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "backend": "local",
        "run_id": run_id,
        "pid": None,
        "returncode": None,
        "command": command_text,
        "wrapper": str(wrapper_path),
        "workdir": str(config.workdir),
        "log_path": str(log_path),
        "result_dir": str(config.result_dir),
        "metadata_path": str(metadata_path),
        "started_at": now_utc_iso(),
        "updated_at": now_utc_iso(),
    }
    atomic_write_json(metadata_path, metadata)
    proc = subprocess.Popen(
        [sys.executable, str(wrapper_path)],
        cwd=str(config.workdir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    metadata["pid"] = int(proc.pid)
    metadata["updated_at"] = now_utc_iso()
    atomic_write_json(metadata_path, metadata)
    _remember_local_process(proc)
    return metadata


def build_watch_snapshot(
    *,
    assignment_id: str,
    run_id: str | None,
    watch_status: str,
    runner_active: bool,
    supervisor_polling: bool,
    remote_screen_names: list[str],
    remote_jsons: list[str],
    local_evidence_paths: dict[str, Any] | None,
    failure_reason: str | None,
    backend: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "assignment_id": assignment_id,
        "run_id": run_id,
        "backend": backend,
        "watch_status": watch_status,
        "runner_active": runner_active,
        "supervisor_polling": supervisor_polling,
        "remote_screen_names": remote_screen_names,
        "remote_jsons": remote_jsons,
        "local_evidence_paths": local_evidence_paths,
        "last_remote_activity_at": now_utc_iso() if remote_screen_names or remote_jsons else None,
        "failure_reason": failure_reason,
        "updated_at": now_utc_iso(),
    }


def write_watch_artifacts(
    *,
    snapshot_path: Path | None,
    event_log_path: Path | None,
    snapshot: dict[str, Any],
    assignment_id: str,
    run_id: str | None,
    event_type: str,
    reason: str,
    source: str,
) -> None:
    if snapshot_path is not None:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(snapshot_path, snapshot)
    if event_log_path is not None:
        append_contract_jsonl(
            event_log_path,
            event_payload(
                event_type=event_type,
                source=source,
                reason=reason,
                assignment_id=assignment_id,
                run_id=run_id,
                watch_status=snapshot["watch_status"],
            ),
        )


def poll_remote(
    *,
    config: RemoteConfig,
    screen_prefixes: list[str],
    result_dir: str,
    assignment_id: str = "",
    run_id: str | None = None,
    snapshot_path: Path | None = None,
    event_log_path: Path | None = None,
    timeout: int = 60,
) -> dict:
    failure_reason = None
    try:
        screen_output = ssh_output(config, "screen -ls || true", timeout=timeout)
        all_screens = parse_screen_ls(screen_output)
        matched = [name for name in all_screens if not screen_prefixes or any(name.startswith(prefix) for prefix in screen_prefixes)]
        gpu_output = ssh_output(
            config,
            "nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader || true",
            timeout=timeout,
        )
        result_listing = ssh_output(config, f"ls -1 {shlex.quote(result_dir)}/*.json 2>/dev/null || true", timeout=timeout)
        remote_jsons = [line.strip() for line in result_listing.splitlines() if line.strip()]
        snapshot = build_watch_snapshot(
            assignment_id=assignment_id,
            run_id=run_id,
            watch_status=classify_watch_status(active=len(matched) > 0, remote_jsons=remote_jsons, local_evidence_paths=None),
            runner_active=len(matched) > 0,
            supervisor_polling=True,
            remote_screen_names=matched,
            remote_jsons=remote_jsons,
            local_evidence_paths=None,
            failure_reason=None,
        )
        snapshot["gpu"] = [line.strip() for line in gpu_output.splitlines() if line.strip()]
        write_watch_artifacts(
            snapshot_path=snapshot_path,
            event_log_path=event_log_path,
            snapshot=snapshot,
            assignment_id=assignment_id,
            run_id=run_id,
            event_type="poll",
            reason="remote_poll",
            source="supervisor",
        )
        return snapshot
    except Exception as exc:  # pragma: no cover - exercised by integration smoke via mocks
        failure_reason = str(exc)[:400]
        snapshot = build_watch_snapshot(
            assignment_id=assignment_id,
            run_id=run_id,
            watch_status="failed",
            runner_active=False,
            supervisor_polling=False,
            remote_screen_names=[],
            remote_jsons=[],
            local_evidence_paths=None,
            failure_reason=failure_reason,
        )
        write_watch_artifacts(
            snapshot_path=snapshot_path,
            event_log_path=event_log_path,
            snapshot=snapshot,
            assignment_id=assignment_id,
            run_id=run_id,
            event_type="poll_failed",
            reason=failure_reason,
            source="supervisor",
        )
        return snapshot


def watch_remote(
    *,
    config: RemoteConfig,
    screen_prefixes: list[str],
    remote_result_dir: str,
    local_result_dir: Path,
    poll_seconds: int,
    snapshot_path: Path | None,
    event_log_path: Path | None,
    max_polls: int,
    assignment_id: str,
    run_id: str | None,
) -> dict:
    last_snapshot: dict[str, Any] = build_watch_snapshot(
        assignment_id=assignment_id,
        run_id=run_id,
        watch_status="idle",
        runner_active=False,
        supervisor_polling=False,
        remote_screen_names=[],
        remote_jsons=[],
        local_evidence_paths=None,
        failure_reason=None,
    )
    for _ in range(max_polls):
        snapshot = poll_remote(
            config=config,
            screen_prefixes=screen_prefixes,
            result_dir=remote_result_dir,
            assignment_id=assignment_id,
            run_id=run_id,
            snapshot_path=snapshot_path,
            event_log_path=event_log_path,
            timeout=90,
        )
        last_snapshot = snapshot
        if snapshot["watch_status"] == "failed":
            return snapshot
        if not snapshot["runner_active"]:
            local_paths: dict[str, str] = {}
            for remote_file in snapshot["remote_jsons"]:
                local_file = local_result_dir / Path(remote_file).name
                scp_fetch(config, remote_file, local_file)
                local_paths[Path(remote_file).name] = str(local_file)
            final_status = "synced" if local_paths else "missing"
            final_snapshot = build_watch_snapshot(
                assignment_id=assignment_id,
                run_id=run_id,
                watch_status=final_status,
                runner_active=False,
                supervisor_polling=False,
                remote_screen_names=snapshot["remote_screen_names"],
                remote_jsons=snapshot["remote_jsons"],
                local_evidence_paths=local_paths or None,
                failure_reason=None if local_paths else "no_remote_results_found",
            )
            final_snapshot["gpu"] = snapshot.get("gpu", [])
            write_watch_artifacts(
                snapshot_path=snapshot_path,
                event_log_path=event_log_path,
                snapshot=final_snapshot,
                assignment_id=assignment_id,
                run_id=run_id,
                event_type="watch_terminal",
                reason=final_status,
                source="supervisor",
            )
            return final_snapshot
        time.sleep(poll_seconds)
    if last_snapshot.get("runner_active"):
        heartbeat_snapshot = dict(last_snapshot)
        heartbeat_snapshot["supervisor_polling"] = False
        heartbeat_snapshot["updated_at"] = now_utc_iso()
        write_watch_artifacts(
            snapshot_path=snapshot_path,
            event_log_path=event_log_path,
            snapshot=heartbeat_snapshot,
            assignment_id=assignment_id,
            run_id=run_id,
            event_type="watch_heartbeat",
            reason="runner_still_active",
            source="supervisor",
        )
        return heartbeat_snapshot
    timeout_snapshot = build_watch_snapshot(
        assignment_id=assignment_id,
        run_id=run_id,
        watch_status="timed_out",
        runner_active=False,
        supervisor_polling=False,
        remote_screen_names=last_snapshot.get("remote_screen_names", []),
        remote_jsons=last_snapshot.get("remote_jsons", []),
        local_evidence_paths=None,
        failure_reason="watch_timeout",
    )
    timeout_snapshot["gpu"] = last_snapshot.get("gpu", [])
    write_watch_artifacts(
        snapshot_path=snapshot_path,
        event_log_path=event_log_path,
        snapshot=timeout_snapshot,
        assignment_id=assignment_id,
        run_id=run_id,
        event_type="watch_timeout",
        reason="timed_out",
        source="supervisor",
    )
    return timeout_snapshot


def poll_local(
    *,
    metadata_path: Path,
    result_dir: Path,
    assignment_id: str = "",
    run_id: str | None = None,
    local_glob: str = "*.json",
    snapshot_path: Path | None = None,
    event_log_path: Path | None = None,
) -> dict[str, Any]:
    if not metadata_path.exists():
        snapshot = build_watch_snapshot(
            assignment_id=assignment_id,
            run_id=run_id,
            watch_status="missing",
            runner_active=False,
            supervisor_polling=False,
            remote_screen_names=[],
            remote_jsons=[],
            local_evidence_paths=None,
            failure_reason="local_run_metadata_missing",
            backend="local",
        )
        write_watch_artifacts(
            snapshot_path=snapshot_path,
            event_log_path=event_log_path,
            snapshot=snapshot,
            assignment_id=assignment_id,
            run_id=run_id,
            event_type="poll_missing",
            reason="local_run_metadata_missing",
            source="local-supervisor",
        )
        return snapshot

    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    effective_run_id = run_id or metadata.get("run_id")
    pid = int(metadata.get("pid") or 0)
    returncode = metadata.get("returncode")
    active = is_process_active(pid) if returncode is None else False
    local_paths = _local_result_paths(result_dir, local_glob)
    if active:
        status = "running"
        failure_reason = None
    elif returncode not in (None, 0):
        status = "failed"
        failure_reason = f"local_process_exit_{returncode}"
    elif local_paths:
        status = "synced"
        failure_reason = None
    else:
        status = "missing"
        failure_reason = "no_local_results_found"
    snapshot = build_watch_snapshot(
        assignment_id=assignment_id,
        run_id=effective_run_id,
        watch_status=status,
        runner_active=active,
        supervisor_polling=True,
        remote_screen_names=[],
        remote_jsons=[],
        local_evidence_paths=local_paths or None,
        failure_reason=failure_reason,
        backend="local",
    )
    snapshot["local_log_path"] = metadata.get("log_path")
    write_watch_artifacts(
        snapshot_path=snapshot_path,
        event_log_path=event_log_path,
        snapshot=snapshot,
        assignment_id=assignment_id,
        run_id=effective_run_id,
        event_type="poll",
        reason="local_poll",
        source="local-supervisor",
    )
    return snapshot


def watch_local(
    *,
    metadata_path: Path,
    result_dir: Path,
    poll_seconds: int,
    snapshot_path: Path | None,
    event_log_path: Path | None,
    max_polls: int,
    assignment_id: str,
    run_id: str | None,
    local_glob: str = "*.json",
) -> dict[str, Any]:
    last_snapshot: dict[str, Any] | None = None
    for _ in range(max_polls):
        snapshot = poll_local(
            metadata_path=metadata_path,
            result_dir=result_dir,
            assignment_id=assignment_id,
            run_id=run_id,
            local_glob=local_glob,
            snapshot_path=snapshot_path,
            event_log_path=event_log_path,
        )
        last_snapshot = snapshot
        if snapshot["watch_status"] in {"synced", "failed", "missing"}:
            terminal = dict(snapshot)
            terminal["supervisor_polling"] = False
            terminal["updated_at"] = now_utc_iso()
            write_watch_artifacts(
                snapshot_path=snapshot_path,
                event_log_path=event_log_path,
                snapshot=terminal,
                assignment_id=assignment_id,
                run_id=terminal.get("run_id"),
                event_type="watch_terminal",
                reason=terminal["watch_status"],
                source="local-supervisor",
            )
            return terminal
        time.sleep(poll_seconds)
    if last_snapshot is not None and last_snapshot.get("runner_active"):
        heartbeat = dict(last_snapshot)
        heartbeat["supervisor_polling"] = False
        heartbeat["updated_at"] = now_utc_iso()
        write_watch_artifacts(
            snapshot_path=snapshot_path,
            event_log_path=event_log_path,
            snapshot=heartbeat,
            assignment_id=assignment_id,
            run_id=heartbeat.get("run_id"),
            event_type="watch_heartbeat",
            reason="runner_still_active",
            source="local-supervisor",
        )
        return heartbeat
    timeout_snapshot = build_watch_snapshot(
        assignment_id=assignment_id,
        run_id=run_id,
        watch_status="timed_out",
        runner_active=False,
        supervisor_polling=False,
        remote_screen_names=[],
        remote_jsons=[],
        local_evidence_paths=None,
        failure_reason="watch_timeout",
        backend="local",
    )
    write_watch_artifacts(
        snapshot_path=snapshot_path,
        event_log_path=event_log_path,
        snapshot=timeout_snapshot,
        assignment_id=assignment_id,
        run_id=run_id,
        event_type="watch_timeout",
        reason="timed_out",
        source="local-supervisor",
    )
    return timeout_snapshot


def cli_poll(args: argparse.Namespace) -> int:
    config = RemoteConfig(args.ssh_key, args.host, args.port)
    snapshot = poll_remote(
        config=config,
        screen_prefixes=args.screen_prefix,
        result_dir=args.remote_result_dir,
        assignment_id=args.assignment_id,
        run_id=args.run_id,
        snapshot_path=Path(args.snapshot_path) if args.snapshot_path else None,
        event_log_path=Path(args.event_log_path) if args.event_log_path else None,
        timeout=args.timeout,
    )
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


def cli_aggregate(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.paths]
    summary = aggregate_result_summaries(paths)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cli_launch_bash(args: argparse.Namespace) -> int:
    config = RemoteConfig(args.ssh_key, args.host, args.port)
    output = run_remote_bash_file(
        config=config,
        remote_workdir=args.remote_workdir,
        script_file=Path(args.script_file),
        timeout=args.timeout,
    )
    print(output)
    return 0


def cli_launch(args: argparse.Namespace) -> int:
    if args.backend == "local":
        config = LocalRunConfig(
            workdir=Path(args.local_workdir),
            result_dir=Path(args.local_result_dir),
            log_dir=Path(args.local_log_dir),
            pid_dir=Path(args.local_pid_dir),
        )
        metadata = launch_local_bash_file(
            config=config,
            script_file=Path(args.script_file),
            run_id=args.run_id,
        )
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        return 0
    if not args.ssh_key or not args.host or not args.remote_workdir:
        raise ValueError("ssh launch requires --ssh-key, --host, and --remote-workdir")
    config = RemoteConfig(args.ssh_key, args.host, args.port)
    output = run_remote_bash_file(
        config=config,
        remote_workdir=args.remote_workdir,
        script_file=Path(args.script_file),
        timeout=args.timeout,
    )
    print(output)
    return 0


def cli_watch(args: argparse.Namespace) -> int:
    config = RemoteConfig(args.ssh_key, args.host, args.port)
    snapshot = watch_remote(
        config=config,
        screen_prefixes=args.screen_prefix,
        remote_result_dir=args.remote_result_dir,
        local_result_dir=Path(args.local_result_dir),
        poll_seconds=args.poll_seconds,
        snapshot_path=Path(args.snapshot_path) if args.snapshot_path else None,
        event_log_path=Path(args.event_log_path) if args.event_log_path else None,
        max_polls=args.max_polls,
        assignment_id=args.assignment_id,
        run_id=args.run_id,
    )
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))

    if args.update_research_logs:
        result_paths = sorted(Path(args.local_result_dir).glob(args.local_glob))
        aggregated = aggregate_result_summaries(result_paths)
        jsonl_item = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "title": args.title,
            "hypothesis": args.hypothesis,
            "changed_files": [],
            "smoke_command": args.smoke_result,
            "full_command": args.full_run_result,
            "primary_metric": args.primary_metric_delta,
            "result_summary": aggregated,
            "keep": args.keep_or_revert,
            "next_best_step": args.next_best_step,
        }
        append_jsonl(Path(args.results_jsonl), jsonl_item)
        block = build_experiment_log_block(
            iteration=args.iteration,
            title=args.title,
            hypothesis=args.hypothesis,
            patch_summary=args.patch_summary,
            smoke_result=args.smoke_result,
            full_run_result=args.full_run_result,
            primary_metric_delta=args.primary_metric_delta,
            guardrail_status=args.guardrail_status,
            keep_or_revert=args.keep_or_revert,
            why=args.why,
            next_best_step=args.next_best_step,
            aggregate_summary=aggregated,
        )
        append_md(Path(args.experiment_log_md), block)
    return 0


def cli_watch_backend(args: argparse.Namespace) -> int:
    if args.backend == "local":
        metadata_path = Path(args.local_metadata_path) if args.local_metadata_path else Path(args.local_pid_dir) / f"{args.run_id or 'latest'}.json"
        snapshot = watch_local(
            metadata_path=metadata_path,
            result_dir=Path(args.local_result_dir),
            poll_seconds=args.poll_seconds,
            snapshot_path=Path(args.snapshot_path) if args.snapshot_path else None,
            event_log_path=Path(args.event_log_path) if args.event_log_path else None,
            max_polls=args.max_polls,
            assignment_id=args.assignment_id,
            run_id=args.run_id,
            local_glob=args.local_glob,
        )
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0
    if not args.ssh_key or not args.host or not args.remote_result_dir or not args.local_result_dir_for_ssh:
        raise ValueError("ssh watch-backend requires --ssh-key, --host, --remote-result-dir, and --local-result-dir-for-ssh")
    config = RemoteConfig(args.ssh_key, args.host, args.port)
    snapshot = watch_remote(
        config=config,
        screen_prefixes=args.screen_prefix,
        remote_result_dir=args.remote_result_dir,
        local_result_dir=Path(args.local_result_dir_for_ssh),
        poll_seconds=args.poll_seconds,
        snapshot_path=Path(args.snapshot_path) if args.snapshot_path else None,
        event_log_path=Path(args.event_log_path) if args.event_log_path else None,
        max_polls=args.max_polls,
        assignment_id=args.assignment_id,
        run_id=args.run_id,
    )
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Research-grade supervisor for remote experiment polling, syncing, and logging.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    poll = sub.add_parser("poll")
    poll.add_argument("--ssh-key", required=True)
    poll.add_argument("--host", required=True)
    poll.add_argument("--port", type=int, default=22)
    poll.add_argument("--screen-prefix", action="append", default=[])
    poll.add_argument("--remote-result-dir", required=True)
    poll.add_argument("--assignment-id", default="")
    poll.add_argument("--run-id")
    poll.add_argument("--snapshot-path")
    poll.add_argument("--event-log-path")
    poll.add_argument("--timeout", type=int, default=60)
    poll.set_defaults(func=cli_poll)

    agg = sub.add_parser("aggregate")
    agg.add_argument("paths", nargs="+")
    agg.set_defaults(func=cli_aggregate)

    launch_any = sub.add_parser("launch")
    launch_any.add_argument("--backend", choices=["local", "ssh"], required=True)
    launch_any.add_argument("--script-file", required=True)
    launch_any.add_argument("--run-id")
    launch_any.add_argument("--timeout", type=int, default=300)
    launch_any.add_argument("--local-workdir", default=".")
    launch_any.add_argument("--local-result-dir", default="results")
    launch_any.add_argument("--local-log-dir", default=".omx/logs/local-runs")
    launch_any.add_argument("--local-pid-dir", default=".omx/state/local-runs")
    launch_any.add_argument("--ssh-key")
    launch_any.add_argument("--host")
    launch_any.add_argument("--port", type=int, default=22)
    launch_any.add_argument("--remote-workdir")
    launch_any.set_defaults(func=cli_launch)

    launch = sub.add_parser("launch-bash")
    launch.add_argument("--ssh-key", required=True)
    launch.add_argument("--host", required=True)
    launch.add_argument("--port", type=int, default=22)
    launch.add_argument("--remote-workdir", required=True)
    launch.add_argument("--script-file", required=True)
    launch.add_argument("--timeout", type=int, default=300)
    launch.set_defaults(func=cli_launch_bash)

    watch = sub.add_parser("watch")
    watch.add_argument("--ssh-key", required=True)
    watch.add_argument("--host", required=True)
    watch.add_argument("--port", type=int, default=22)
    watch.add_argument("--screen-prefix", action="append", default=[])
    watch.add_argument("--remote-result-dir", required=True)
    watch.add_argument("--local-result-dir", required=True)
    watch.add_argument("--assignment-id", default="")
    watch.add_argument("--run-id")
    watch.add_argument("--local-glob", default="*.json")
    watch.add_argument("--poll-seconds", type=int, default=300)
    watch.add_argument("--max-polls", type=int, default=120)
    watch.add_argument("--snapshot-path")
    watch.add_argument("--event-log-path")
    watch.add_argument("--update-research-logs", action="store_true")
    watch.add_argument("--iteration", type=int, default=0)
    watch.add_argument("--title", default="Supervisor watch summary")
    watch.add_argument("--hypothesis", default="remote run should finish and preserve current advantage")
    watch.add_argument("--patch-summary", default="no code patch in watch-only round")
    watch.add_argument("--smoke-result", default="reused existing harness")
    watch.add_argument("--full-run-result", default="remote watch completed")
    watch.add_argument("--primary-metric-delta", default="see aggregated summary")
    watch.add_argument("--guardrail-status", default="ok")
    watch.add_argument("--keep-or-revert", default="keep")
    watch.add_argument("--why", default="watch completed")
    watch.add_argument("--next-best-step", default="decide next round from aggregated summary")
    watch.add_argument("--results-jsonl", default="research/results.jsonl")
    watch.add_argument("--experiment-log-md", default="research/EXPERIMENT_LOG.md")
    watch.set_defaults(func=cli_watch)

    watch_any = sub.add_parser("watch-backend")
    watch_any.add_argument("--backend", choices=["local", "ssh"], required=True)
    watch_any.add_argument("--local-metadata-path")
    watch_any.add_argument("--local-pid-dir", default=".omx/state/local-runs")
    watch_any.add_argument("--local-result-dir", default="results")
    watch_any.add_argument("--local-glob", default="*.json")
    watch_any.add_argument("--poll-seconds", type=int, default=300)
    watch_any.add_argument("--max-polls", type=int, default=120)
    watch_any.add_argument("--assignment-id", default="")
    watch_any.add_argument("--run-id")
    watch_any.add_argument("--snapshot-path")
    watch_any.add_argument("--event-log-path")
    watch_any.add_argument("--ssh-key")
    watch_any.add_argument("--host")
    watch_any.add_argument("--port", type=int, default=22)
    watch_any.add_argument("--screen-prefix", action="append", default=[])
    watch_any.add_argument("--remote-result-dir")
    watch_any.add_argument("--local-result-dir-for-ssh")
    watch_any.set_defaults(func=cli_watch_backend)

    return ap


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
