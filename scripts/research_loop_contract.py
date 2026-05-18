#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = 1
ROLE_VALUES = {"reader", "runner"}
RUN_PHASE_VALUES = {"reader", "runner", "watch", "done", "abandoned", "needs_human"}
RESUME_MODE_VALUES = {"fresh", "resume_same_role"}
PROMPT_TARGET_VALUES = {"reader", "runner", "next_actual_agent"}
WATCH_STATUS_VALUES = {
    "idle",
    "submitted",
    "running",
    "results_ready",
    "synced",
    "timed_out",
    "missing",
    "failed",
}
EXECUTION_BACKEND_VALUES = {"local", "ssh"}


@dataclass(frozen=True)
class ArtifactPaths:
    runtime_root: Path
    state_root: Path
    logs_root: Path
    reports_root: Path
    prompts_root: Path
    commands_root: Path
    synced_results_root: Path
    autoloop_root: Path
    last_launch_metadata: Path
    last_agent_message: Path
    workspace_root: Path
    roles_root: Path
    reader_role_root: Path
    runner_role_root: Path
    person_program: Path
    agent_program: Path
    watch_snapshot: Path
    watch_events: Path
    task_state: Path
    ai_worklog: Path


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compact_text_summary(label: str, path: Path, text: str, max_excerpt: int = 120) -> dict[str, Any]:
    return {
        "label": label,
        "path": str(path),
        "chars": len(text),
        "sha256": text_sha256(text),
    }


def render_compact_summary(summary: dict[str, Any]) -> str:
    return (
        f"{summary['label']}: path={summary['path']}, chars={summary['chars']}, "
        f"sha256={summary['sha256']}"
    )


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _has_dense_question_marks(text: str) -> bool:
    stripped = text.replace("\n", "")
    suspicious_markers = ["????", "�", "鈥", "鍙", "绛", "鏈", "褰撳"]
    return any(marker in stripped for marker in suspicious_markers)


def validate_person_program_text(text: str) -> None:
    if "# person_program" not in text.lower():
        raise ValueError("person_program missing title sentinel")
    if "## " not in text:
        raise ValueError("person_program missing section headings")
    if len(text.strip()) < 120:
        raise ValueError("person_program is too short to be a valid control document")
    if _has_dense_question_marks(text):
        raise ValueError("person_program appears content-corrupted with replacement '?' text")


def read_validated_text(path: Path, kind: str) -> str:
    text = read_text(path)
    if kind == "person_program":
        validate_person_program_text(text)
    elif kind == "agent_program":
        pass  # agent_program.md is a soft-constraint artifact — no validation
    else:
        raise ValueError(f"unknown guarded text kind: {kind}")
    return text


def require_enum(value: str | None, allowed: set[str], field: str) -> str:
    if value not in allowed:
        raise ValueError(f"invalid {field}: {value!r}")
    return str(value)


def resolve_execution_backend(config: dict[str, Any] | None = None) -> str:
    config = config or {}
    execution = config.get("execution", {}) if isinstance(config, dict) else {}
    explicit = execution.get("backend") if isinstance(execution, dict) else None
    if explicit is None or str(explicit).strip() == "":
        remote = config.get("remote", {}) if isinstance(config, dict) else {}
        backend = "ssh" if isinstance(remote, dict) and remote else "local"
    else:
        backend = str(explicit).strip().lower()
    return require_enum(backend, EXECUTION_BACKEND_VALUES, "execution.backend")


def resolve_artifact_paths(root: Path, config: dict[str, Any] | None = None) -> ArtifactPaths:
    config = config or {}
    artifacts = config.get("artifacts", {}) if isinstance(config, dict) else {}
    runtime = config.get("runtime", {}) if isinstance(config, dict) else {}

    inferred_runtime_root = ".subphd"
    explicit_legacy_hints = [
        str(artifacts.get("loop_state", "")),
        str(artifacts.get("watch_snapshot", "")),
        str(artifacts.get("watch_events", "")),
        str(artifacts.get("run_state", "")),
        str(artifacts.get("ai_worklog", "")),
    ]
    if not runtime.get("root") and any(hint.startswith(".omx/") for hint in explicit_legacy_hints):
        inferred_runtime_root = ".omx"

    runtime_root_name = str(runtime.get("root", inferred_runtime_root))
    runtime_root = (root / runtime_root_name).resolve()
    state_root = (root / str(runtime.get("state_root", str(Path(runtime_root_name) / "state")))).resolve()
    logs_root = (root / str(runtime.get("logs_root", str(Path(runtime_root_name) / "logs")))).resolve()
    reports_root = (root / str(runtime.get("reports_root", str(Path(runtime_root_name) / "reports")))).resolve()
    prompts_root = (root / str(runtime.get("prompts_root", str(Path(runtime_root_name) / "prompts")))).resolve()
    commands_root = (root / str(runtime.get("commands_root", str(Path(runtime_root_name) / "commands")))).resolve()
    synced_results_root = (root / str(runtime.get("synced_results_root", str(Path(runtime_root_name) / "synced-results")))).resolve()
    autoloop_root = (root / str(runtime.get("autoloop_root", str(Path(runtime_root_name) / "autoloop")))).resolve()
    workspace_root = (root / str(runtime.get("workspace_root", "."))).resolve()
    roles_root = (root / str(runtime.get("roles_root", "roles"))).resolve()
    reader_role_root = (roles_root / "reader").resolve()
    runner_role_root = (roles_root / "runner").resolve()

    def pick(name: str, default: str) -> Path:
        raw = artifacts.get(name, default)
        return (root / raw).resolve()

    return ArtifactPaths(
        runtime_root=runtime_root,
        state_root=state_root,
        logs_root=logs_root,
        reports_root=reports_root,
        prompts_root=prompts_root,
        commands_root=commands_root,
        synced_results_root=synced_results_root,
        autoloop_root=autoloop_root,
        last_launch_metadata=(runtime_root / "last-launch-metadata.json").resolve(),
        last_agent_message=(runtime_root / "last-research-agent-message.txt").resolve(),
        workspace_root=workspace_root,
        roles_root=roles_root,
        reader_role_root=reader_role_root,
        runner_role_root=runner_role_root,
        person_program=pick("person_program", "person_program.md"),
        agent_program=pick("agent_program", "agent_program.md"),
        watch_snapshot=pick("watch_snapshot", f"{runtime_root.name}/state/research_watch_snapshot.json"),
        watch_events=pick("watch_events", f"{runtime_root.name}/state/research_watch_events.jsonl"),
        task_state=pick("task_state", f"{runtime_root.name}/state/task-state.json"),
        ai_worklog=pick("ai_worklog", f"{runtime_root.name}/logs/ai-worklog.md"),
    )


def default_task_state(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    backend = resolve_execution_backend(config)
    default_hours = float(config.get("default_hours", 10))
    default_max_runs = int(config.get("default_max_runs", 30))
    loop_cfg = config.get("loop", {}) if isinstance(config, dict) else {}
    runner_turn_cap = int(loop_cfg.get("runner_turn_cap", 4))
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "reader",
        "next_action": "reader",
        "current_objective": "",
        "success_condition": "",
        "reader_iteration": 0,
        "reader_iteration_cap": default_max_runs,
        "runner_iteration": 0,
        "runner_iteration_cap": runner_turn_cap,
        "window_role": "reader",
        "resume_count": 0,
        "resume_budget": 3,
        "execution_backend": backend,
        "remote_status": "idle",
        "run_id": None,
        "last_result_summary": "",
        "last_error": None,
        "repair_count": 0,
        "prompt_contract_hash": None,
        "pending_human_prompt": None,
        "remaining_hours": default_hours,
        "remaining_max_runs": default_max_runs,
        "sprint_contract": None,
        "runner_done_reason": None,
        "no_improvement_count": 0,
        "updated_at": now_utc_iso(),
    }


def default_watch_snapshot() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "assignment_id": "",
        "run_id": None,
        "backend": None,
        "watch_status": "idle",
        "runner_active": False,
        "supervisor_polling": False,
        "remote_screen_names": [],
        "remote_jsons": [],
        "local_evidence_paths": None,
        "last_remote_activity_at": None,
        "failure_reason": None,
        "updated_at": now_utc_iso(),
    }


def event_payload(*, event_type: str, source: str, reason: str, assignment_id: str | None = None, run_id: str | None = None, watch_status: str = "idle", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "assignment_id": assignment_id,
        "run_id": run_id,
        "watch_status": watch_status,
        "event_type": event_type,
        "reason": reason,
        "source": source,
        "timestamp": now_utc_iso(),
    }
    if extra:
        payload.update(extra)
    return payload


def evaluate_success_condition(success_condition: Any, task_state: dict[str, Any]) -> tuple[bool, str]:
    """Return (is_satisfied, details). Legacy string conditions always return False."""
    if isinstance(success_condition, str) or not isinstance(success_condition, dict):
        return False, "legacy_string_condition_cannot_machine_evaluate"
    mode = success_condition.get("mode", "all")
    conditions = success_condition.get("conditions", [])
    if not isinstance(conditions, list) or len(conditions) == 0:
        return False, "no_conditions_defined"
    sprint_contract = task_state.get("sprint_contract")
    metrics = {}
    if isinstance(sprint_contract, dict):
        metrics = sprint_contract.get("metrics", {}) or {}
    results: list[bool] = []
    details: list[str] = []
    for i, cond in enumerate(conditions):
        if "metric" in cond:
            actual = metrics.get(cond["metric"])
            op = cond.get("op", ">=")
            threshold = cond.get("threshold", 0)
            ok = _eval_metric_condition(actual, op, threshold)
            results.append(ok)
            details.append(f"cond[{i}]: {cond['metric']}={actual} {op} {threshold} -> {ok}")
        elif "artifact" in cond:
            expected_exists = cond.get("exists", True)
            actual_exists = Path(cond["artifact"]).exists()
            ok = actual_exists == expected_exists
            results.append(ok)
            details.append(f"cond[{i}]: artifact={cond['artifact']} exists={actual_exists} expected={expected_exists} -> {ok}")
        else:
            results.append(False)
            details.append(f"cond[{i}]: unknown_condition_type")
    if mode == "all":
        return all(results), " | ".join(details)
    if mode == "any":
        return any(results), " | ".join(details)
    return False, f"unknown_mode={mode}"


def _eval_metric_condition(actual: float | None, op: str, threshold: float) -> bool:
    if actual is None:
        return False
    if op == ">=":
        return float(actual) >= float(threshold)
    if op == ">":
        return float(actual) > float(threshold)
    if op == "<=":
        return float(actual) <= float(threshold)
    if op == "<":
        return float(actual) < float(threshold)
    if op == "==":
        return float(actual) == float(threshold)
    return False


def compute_prompt_contract_hash(person_program: str, agent_program: str, role: str, task_state: dict[str, Any]) -> str:
    require_enum(role, ROLE_VALUES, "role")
    basis = {
        "person_program": person_program,
        "agent_program": agent_program,
        "role": role,
        "task_state": dict(task_state),
    }
    basis["task_state"].pop("updated_at", None)
    basis["task_state"].pop("pending_human_prompt", None)
    return hashlib.sha256(stable_json(basis).encode("utf-8")).hexdigest()


def compute_resume_key(role: str, task_state: dict[str, Any], agent_program_hash: str, has_new_human_prompt: bool) -> str:
    sprint_contract = task_state.get("sprint_contract") or {}
    sprint_id = sprint_contract.get("sprint_id") if isinstance(sprint_contract, dict) else None
    basis = {
        "role": role,
        "sprint_id": sprint_id,
        "window_role": task_state.get("window_role"),
        "agent_program_hash": agent_program_hash,
        "has_new_human_prompt": has_new_human_prompt,
    }
    return hashlib.sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def validate_watch_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported watch snapshot schema_version")
    for field in ["assignment_id", "watch_status", "runner_active", "supervisor_polling", "remote_screen_names", "remote_jsons", "local_evidence_paths", "updated_at"]:
        if field not in data:
            raise ValueError(f"missing {field}")
    require_enum(data.get("watch_status"), WATCH_STATUS_VALUES, "watch_status")
    backend = data.get("backend")
    if backend is not None:
        require_enum(backend, EXECUTION_BACKEND_VALUES, "backend")
    if not isinstance(data.get("assignment_id"), str):
        raise ValueError("assignment_id must be a string")
    local_evidence = data.get("local_evidence_paths")
    if local_evidence is not None:
        if not isinstance(local_evidence, dict):
            raise ValueError("local_evidence_paths must be a dict or null")
        for key, value in local_evidence.items():
            if not isinstance(key, str) or not isinstance(value, str) or not value:
                raise ValueError("malformed local_evidence_paths entry")
            if "@" in value or value.startswith("ssh://"):
                raise ValueError("local_evidence_paths must point to local files")
    return data


def validate_task_state(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported task state schema_version")
    required = [
        "phase", "next_action", "current_objective", "success_condition",
        "reader_iteration", "reader_iteration_cap",
        "runner_iteration", "runner_iteration_cap",
        "window_role", "resume_count", "resume_budget",
        "execution_backend", "remote_status", "run_id",
        "last_result_summary", "last_error", "repair_count",
        "prompt_contract_hash", "remaining_hours", "remaining_max_runs",
        "sprint_contract", "runner_done_reason", "no_improvement_count",
        "updated_at",
    ]
    for field in required:
        if field not in data:
            raise ValueError(f"missing {field}")
    require_enum(data.get("phase"), RUN_PHASE_VALUES, "phase")
    require_enum(data.get("window_role"), ROLE_VALUES, "window_role")
    if "execution_backend" in data:
        require_enum(data.get("execution_backend"), EXECUTION_BACKEND_VALUES, "execution_backend")
    # Validate sprint_contract if present
    sc = data.get("sprint_contract")
    if sc is not None:
        if not isinstance(sc, dict):
            raise ValueError("sprint_contract must be a dict or null")
        scond = sc.get("success_condition")
        if isinstance(scond, dict):
            mode = scond.get("mode", "all")
            if mode not in {"all", "any"}:
                raise ValueError(f"success_condition.mode must be 'all' or 'any', got {mode!r}")
            conditions = scond.get("conditions")
            if not isinstance(conditions, list) or len(conditions) == 0:
                raise ValueError("success_condition.conditions must be a non-empty list")
    # Validate pending_human_prompt if present
    pending = data.get("pending_human_prompt")
    if pending is not None:
        if not isinstance(pending, dict):
            raise ValueError("pending_human_prompt must be a dict or null")
        require_enum(pending.get("target"), PROMPT_TARGET_VALUES, "pending_human_prompt.target")
        if not isinstance(pending.get("text"), str) or not pending.get("text").strip():
            raise ValueError("pending_human_prompt.text must be a non-empty string")
    return data


def load_task_state(path: Path) -> dict[str, Any]:
    return validate_task_state(read_json(path))


def append_ai_worklog_entry(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    block = [
        f"## {payload.get('role', 'unknown')} | {payload.get('start_time', now_utc_iso())}",
        f"- Current objective: {payload.get('current_objective', '')}",
        f"- Runner iteration: {payload.get('runner_iteration', 0)}/{payload.get('runner_iteration_cap', 0)}",
        f"- Reader iteration: {payload.get('reader_iteration', 0)}/{payload.get('reader_iteration_cap', 0)}",
        f"- Success condition: {payload.get('success_condition', '')}",
        f"- Remote status: {payload.get('remote_status', '')}",
        f"- Latest result summary: {payload.get('latest_result_summary', '')}",
        f"- Next action: {payload.get('next_action', '')}",
    ]
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(block) + "\n\n")


def ensure_program_files(root: Path, config: dict[str, Any] | None = None, *, allow_bootstrap_agent: bool = True) -> ArtifactPaths:
    paths = resolve_artifact_paths(root, config)
    paths.workspace_root.mkdir(parents=True, exist_ok=True)
    if not paths.person_program.exists():
        raise FileNotFoundError("Missing person_program.md. Create it before starting the sub-PHD runtime loop.")
    read_validated_text(paths.person_program, "person_program")
    if not paths.agent_program.exists():
        if not allow_bootstrap_agent:
            raise FileNotFoundError("Missing agent_program.md. Start via autoloop to bootstrap it, or restore it from version control.")
        atomic_write_text(paths.agent_program, "# agent_program.md\n\n## Current Strategy\n- Reader may edit this file directly.\n- Default posture: prioritize explicit, traceable, budget-aware research progress.\n\n## Revision Suggestions\n- None yet.\n")
        append_jsonl(
            paths.watch_events,
            event_payload(
                event_type="bootstrap_agent_program",
                source="autoloop",
                reason="missing_agent_program_bootstrap",
                assignment_id=None,
                run_id=None,
                watch_status="idle",
            ),
        )
    return paths


def require_runtime_artifacts(root: Path, config: dict[str, Any] | None = None) -> ArtifactPaths:
    paths = ensure_program_files(root, config, allow_bootstrap_agent=False)
    missing = [str(p) for p in [paths.task_state] if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Missing runtime artifacts: {', '.join(missing)}. Start via autoloop first.")
    return paths


def bootstrap_state_artifacts(root: Path, config: dict[str, Any] | None = None) -> ArtifactPaths:
    paths = ensure_program_files(root, config, allow_bootstrap_agent=True)
    for directory in [
        paths.runtime_root,
        paths.state_root,
        paths.logs_root,
        paths.reports_root,
        paths.prompts_root,
        paths.commands_root,
        paths.synced_results_root,
        paths.autoloop_root,
        paths.workspace_root,
    ]:
        directory.mkdir(parents=True, exist_ok=True)
    if not paths.watch_snapshot.exists():
        atomic_write_json(paths.watch_snapshot, default_watch_snapshot())
    if not paths.watch_events.exists():
        paths.watch_events.parent.mkdir(parents=True, exist_ok=True)
        paths.watch_events.touch()
    if not paths.task_state.exists():
        atomic_write_json(paths.task_state, default_task_state(config))
    return paths


def reset_runtime_state(paths: ArtifactPaths, config: dict[str, Any] | None = None, *, reason: str = "fresh_task_start") -> dict[str, Any]:
    watch_snapshot = default_watch_snapshot()
    watch_snapshot["updated_at"] = now_utc_iso()
    task_state = default_task_state(config)
    task_state["updated_at"] = now_utc_iso()
    atomic_write_json(paths.watch_snapshot, watch_snapshot)
    atomic_write_json(paths.task_state, task_state)
    return task_state


def load_watch_snapshot(path: Path) -> dict[str, Any]:
    return validate_watch_snapshot(read_json(path))


def classify_watch_status(*, active: bool, remote_jsons: list[str], local_evidence_paths: dict[str, Any] | None = None, timed_out: bool = False, failure_reason: str | None = None) -> str:
    if failure_reason:
        return "failed"
    if timed_out:
        return "timed_out"
    if active and remote_jsons:
        return "results_ready"
    if active:
        return "running"
    if local_evidence_paths:
        return "synced"
    if remote_jsons:
        return "results_ready"
    return "missing"
