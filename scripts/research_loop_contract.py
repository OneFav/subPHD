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
RUN_PHASE_VALUES = {"reader", "runner", "watch"}
RESUME_MODE_VALUES = {"fresh", "resume_same_role"}
PROMPT_TARGET_VALUES = {"reader", "runner", "next_actual_agent"}
OBSERVABILITY_MERGE_STATUS_VALUES = {"not_found", "merged", "invalid_sidecar", "merge_failed"}
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

DEFAULT_AGENT_PROGRAM = """# agent_program.md

## Current Strategy
- Reader may edit this file directly.
- Default posture: prioritize explicit, traceable, budget-aware research progress.
- Prefer reversible, evidence-rich experimental steps.

## Revision Suggestions
- None yet. The runner must add English paper-revision suggestions before handoff.
"""

DEFAULT_READER_SKILLS: dict[str, str] = {
    "reader-handoff": """---
name: reader-handoff
description: Reader role helper for turning shared runtime evidence into the next bounded objective.
---

# Reader Handoff

Use this project-local role skill to keep reader work concrete:

- inspect the current authoritative handoff first, then current authoritative artifacts, then only consult generic reports/archive if those are insufficient
- tighten `agent_program.md` into a runner-ready assignment
- when the next runner turn is remote, define the compact core artifact set that should remain in `remote_result_dir`
- instruct runner to delete non-essential process files before watch sync whenever those files do not need to come back locally
- write `expected_output` and `why` in plain language, naming the concrete experiment, metric, file, or decision rather than vague process wording
- prefer bounded objectives over abstract future planning
""",
    "experiment-plan": """---
name: experiment-plan
description: Turn the current sub-PHD direction into a compact claim-to-evidence run plan for the next runner turn.
---

# Experiment Plan

Use when the next step is still fuzzy and runner needs a tighter execution contract.

- read the current authoritative handoff first, then `person_program.md`, `agent_program.md`, `.subphd/state/run-state.json`, and only then fall back to generic recent reports/synced results if needed
- translate the current objective into: claim, evidence needed, concrete run order, stop condition, and artifact checklist
- keep the plan compact: one primary question, a small number of runs, and explicit success/failure criteria
- name the exact experiment, metric, file, or decision the next run must produce
- write the resulting bounded plan back into `agent_program.md` in language runner can execute immediately
""",
    "analyze-results": """---
name: analyze-results
description: Summarize synced experiment outputs into concrete comparisons, deltas, and anomalies for reader decisions.
---

# Analyze Results

Use when new outputs arrive from runner or watch sync.

- inspect the current authoritative handoff and current-window evidence first; only use generic recent reports/archive as fallback context
- extract the primary metric, the comparison baseline, and the observed delta instead of listing raw files only
- flag suspicious patterns clearly: missing outputs, regressions, instability, or results that do not answer the intended question
- update `expected_output`, `why`, and the next handoff using plain language a human can scan quickly
- prefer a short table or bullet summary over vague prose
""",
    "result-to-claim": """---
name: result-to-claim
description: Judge what the latest results actually support before reader authorizes the next run.
---

# Result to Claim

Use after a meaningful run completes and before expanding scope.

- compare the intended claim in `agent_program.md` with the evidence that actually came back
- decide explicitly: supported, partially supported, not supported, or still unclear
- name what evidence is missing if the answer is still unclear
- turn the judgment into the next bounded action: confirm, repair, ablate, or pivot
- write the judgment in plain language that names the exact experiment, metric, file, or decision
""",
}

DEFAULT_RUNNER_SKILLS: dict[str, str] = {
    "runner-implementation": """---
name: runner-implementation
description: Runner role helper for implementing and validating bounded changes in the repo working tree.
---

# Runner Implementation

Use this project-local role skill to keep runner work grounded:

- implement the current bounded assignment in the repo working tree
- validate with the smallest meaningful checks before handoff
- record what changed and what evidence was gathered
- before the remote run ends, prune `remote_result_dir` so only the compact core artifacts remain for watch sync
- delete unnecessary intermediate/process files by default
- keep only the final decision/metrics/summary/manifest style artifacts unless the assignment explicitly requires more
- if a large artifact might matter later, leave a small retained note about it rather than keeping the bulky file in `remote_result_dir`
- for `expected_output` and `why`, write short plain-language lines that name the exact experiment, metric, file, or decision; avoid vague process-speak
""",
    "experiment-bridge": """---
name: experiment-bridge
description: Turn a bounded reader assignment into code changes, a remote run, and a compact evidence package.
---

# Experiment Bridge

Use when reader has already narrowed the task and runner must execute it.

- implement only the missing code, config, or script changes required for the assigned run
- launch the smallest remote experiment that answers the current question before widening scope
- keep the run tied to a clear stop condition and expected artifact list from `agent_program.md`
- collect a compact evidence bundle: decision, core metrics, summary, manifest, and any explicitly requested files
- before exit, prune `remote_result_dir` so watch sync only brings back what reader actually needs
""",
    "monitor-experiment": """---
name: monitor-experiment
description: Check remote run progress and collect only the compact evidence needed for sub-PHD decisions.
---

# Monitor Experiment

Use while a remote run is active or when watch is waiting on completion.

- check whether the remote process is still alive, progressing, stalled, or failed
- report the current state in plain language: what is running, what finished, and what is blocked
- prefer concise progress indicators such as the latest completed step, elapsed time, and newest result file
- if the remote run already produced enough evidence, say so explicitly instead of waiting for every optional artifact
- keep notes compatible with `.subphd/state/research_watch_snapshot.json` and the dashboard timeline
""",
    "training-check": """---
name: training-check
description: Detect obvious run-quality failures early so runner does not waste GPU time.
---

# Training Check

Use during longer remote runs when training quality is uncertain.

- inspect the latest metrics/logs for failure signals such as NaN, divergence, flatlined progress, or idle execution
- report the exact metric or log line that indicates the problem
- if the run is clearly broken, stop and hand back a compact failure summary rather than burning more time
- if the run looks healthy, say which metric trend supports continuing
- keep the summary short, concrete, and understandable to a human reading sub-PHD
""",
}


DEFAULT_ROLE_SURFACES: dict[str, dict[str, Any]] = {
    "reader": {
        "agents": """# Reader Role Surface\n\nYou are the project-local READER role.\n\n## Purpose\n- Analyze the current state of the repo-local runtime and control artifacts.\n- Refine `agent_program.md` and the next bounded objective.\n- Do not perform benchmark redesign or broad speculative replanning unless the current evidence forces it.\n\n## Must preserve\n- Shared `person_program.md` + `agent_program.md` control model\n- Direct repo-root ownership for code and artifacts (no separate workspace directory)\n- Current benchmark semantics and runtime contract\n- Treat the current authoritative handoff as the first continuity source; use generic recent reports/archive only as fallback context\n- When handing off a remote run, specify the compact core artifact set that should survive in `remote_result_dir`, so runner can delete non-essential process files before watch sync\n- When you set or revise `expected_output` and `why`, write them in plain language and name the exact experiment, metric, file, or decision the human should understand\n""",
        "skills": DEFAULT_READER_SKILLS,
    },
    "runner": {
        "agents": """# Runner Role Surface\n\nYou are the project-local RUNNER role.\n\n## Purpose\n- Implement and verify bounded changes in the repo working tree.\n- Keep work focused on the current assignment and runtime contract.\n- Prefer real implementation + validation over further strategic churn.\n\n## Must preserve\n- Shared `person_program.md` + `agent_program.md` control model\n- Direct repo-root ownership for code and artifacts (no separate workspace directory)\n- Current benchmark semantics and runtime contract\n- Before ending a remote run, clean `remote_result_dir` so watch sync only sees the compact core artifacts that really need to come back locally\n- Delete bulky intermediate/process files by default; only keep the final core result set such as decisions, metrics, summaries, manifests, and other explicitly needed evidence\n- If a large artifact may matter later, prefer leaving a compact summary/manifest note that points to it rather than retaining the bulky file in `remote_result_dir`\n- When writing dashboard fields such as `expected_output` and `why`, use plain language, name the exact experiment/check/artifact/metric involved, and avoid vague filler like 'the process requires this'\n""",
        "skills": DEFAULT_RUNNER_SKILLS,
    },
}


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
    omx_compat_root: Path
    legacy_runtime_root: Path
    person_program: Path
    agent_program: Path
    loop_state: Path
    watch_snapshot: Path
    watch_events: Path
    run_state: Path
    ai_worklog: Path
    agent_observability: Path


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_big_round_id() -> str:
    return f"big-round-{uuid4().hex[:12]}"


def new_role_window_id(role: str) -> str:
    safe_role = require_enum(role, ROLE_VALUES, "role")
    return f"{safe_role}-window-{uuid4().hex[:12]}"


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


def validate_agent_program_text(text: str) -> None:
    if "# agent_program.md" not in text:
        raise ValueError("agent_program missing title sentinel")
    lowered = text.lower()
    if "## current strategy" not in lowered:
        raise ValueError("agent_program missing strategy section")
    if "## revision suggestions" not in lowered:
        raise ValueError("agent_program missing revision section")
    allowed_control_terms = ["runner", "reader", "paper", "strategy", "revision"]
    if not any(term in text or term in lowered for term in allowed_control_terms):
        raise ValueError("agent_program missing required control terms")
    if _has_dense_question_marks(text):
        raise ValueError("agent_program appears content-corrupted with replacement '?' text")


def read_validated_text(path: Path, kind: str) -> str:
    text = read_text(path)
    if kind == "person_program":
        validate_person_program_text(text)
    elif kind == "agent_program":
        validate_agent_program_text(text)
    else:
        raise ValueError(f"unknown guarded text kind: {kind}")
    return text


def require_enum(value: str | None, allowed: set[str], field: str) -> str:
    if value not in allowed:
        raise ValueError(f"invalid {field}: {value!r}")
    return str(value)


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
        str(artifacts.get("agent_observability", "")),
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
    omx_compat_root = (root / str(runtime.get("compat_root", ".omx"))).resolve()
    legacy_runtime_root = (root / str(runtime.get("legacy_runtime_root", ".autoresearch"))).resolve()

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
        omx_compat_root=omx_compat_root,
        legacy_runtime_root=legacy_runtime_root,
        person_program=pick("person_program", "person_program.md"),
        agent_program=pick("agent_program", "agent_program.md"),
        loop_state=pick("loop_state", f"{runtime_root.name}/state/research_loop_state.json"),
        watch_snapshot=pick("watch_snapshot", f"{runtime_root.name}/state/research_watch_snapshot.json"),
        watch_events=pick("watch_events", f"{runtime_root.name}/state/research_watch_events.jsonl"),
        run_state=pick("run_state", f"{runtime_root.name}/state/run-state.json"),
        ai_worklog=pick("ai_worklog", f"{runtime_root.name}/logs/ai-worklog.md"),
        agent_observability=pick("agent_observability", f"{runtime_root.name}/state/agent-observability.json"),
    )


def default_remaining_budget(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    remote = config.get("remote", {}) if isinstance(config, dict) else {}
    loop_cfg = config.get("loop", {}) if isinstance(config, dict) else {}
    return {
        "hours": float(config.get("default_hours", 10)),
        "max_runs": int(config.get("default_max_runs", 30)),
        "gpu_count": int(loop_cfg.get("gpu_count", remote.get("gpu_count", 4))),
    }


def default_loop_state(config: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "next_agent": "reader",
        "remaining_global_budget": default_remaining_budget(config),
        "last_transition_reason": "bootstrap",
        "last_watch_status": "idle",
        "last_resume_mode": "fresh",
        "last_prompt_role": None,
        "last_prompt_path": None,
        "prompt_contract_hash": None,
        "big_round_id": new_big_round_id(),
        "window_role": "reader",
        "role_window_id": new_role_window_id("reader"),
        "resume_budget": 3,
        "resume_count": 0,
        "last_authoritative_handoff_path": None,
        "last_rollover_at": None,
        "last_rollover_reason": None,
        "updated_at": now_utc_iso(),
    }


def default_run_state(config: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "reader",
        "role_context_mode": "isolated",
        "current_objective": "",
        "agent_program_ref": None,
        "reader_iteration": 0,
        "reader_iteration_cap": int((config or {}).get("default_max_runs", 30)),
        "runner_iteration": 0,
        "runner_iteration_cap": 1,
        "success_condition": "",
        "run_id": None,
        "remote_status": "idle",
        "last_result_summary": "",
        "next_action": "reader",
        "pending_human_prompt": None,
        "repair_count": 0,
        "last_error": None,
        "updated_at": now_utc_iso(),
    }


def default_agent_observability() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "segments": [],
        "updated_at": now_utc_iso(),
    }


def default_watch_snapshot() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "assignment_id": "",
        "run_id": None,
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


def normalize_authoritative_handoff_payload(payload: dict[str, Any] | None) -> dict[str, Any] | str:
    if not payload:
        return "NO_AUTHORITATIVE_HANDOFF"
    normalized = dict(payload)
    normalized.pop("prompt_contract_basis_sha256", None)
    return normalized


def authoritative_handoffs_root(paths: ArtifactPaths) -> Path:
    return paths.reports_root / "authoritative-handoffs"


def build_authoritative_handoff_path(paths: ArtifactPaths, loop_state: dict[str, Any]) -> Path:
    big_round_id = str(loop_state.get("big_round_id") or new_big_round_id())
    window_role = require_enum(str(loop_state.get("window_role") or "reader"), ROLE_VALUES, "window_role")
    role_window_id = str(loop_state.get("role_window_id") or new_role_window_id(window_role))
    return authoritative_handoffs_root(paths) / f"authoritative-handoff-{big_round_id}-{window_role}-{role_window_id}.json"


def load_authoritative_handoff_payload(path: Path | None, *, expected_big_round_id: str | None = None, expected_window_role: str | None = None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    payload = read_json(path)
    required = [
        "schema_version",
        "big_round_id",
        "role_window_id",
        "window_role",
        "source_role",
        "generated_at",
        "current_objective",
        "current_conclusions",
        "next_step_recommendation",
        "authoritative_artifacts",
        "key_evidence",
        "failed_or_do_not_repeat",
        "open_uncertainties",
        "person_program_reader_judgment",
        "agent_program_runner_judgment",
        "planning_guidance",
        "handoff_summary_text",
        "prompt_contract_basis_sha256",
    ]
    for field in required:
        if field not in payload:
            raise ValueError(f"authoritative handoff missing {field}")
    if expected_big_round_id and payload.get("big_round_id") != expected_big_round_id:
        raise ValueError("authoritative handoff big_round_id mismatch")
    if expected_window_role and payload.get("window_role") != expected_window_role:
        raise ValueError("authoritative handoff window_role mismatch")
    return payload


def compute_prompt_contract_hash(person_program: str, agent_program: str, role: str, assignment_payload: dict[str, Any] | None, authoritative_handoff: dict[str, Any] | None = None) -> str:
    require_enum(role, ROLE_VALUES, "role")
    basis = {
        "person_program": person_program,
        "agent_program": agent_program,
        "role": role,
        "assignment": build_canonical_contract_assignment(assignment_payload or {}, role),
        "authoritative_handoff": normalize_authoritative_handoff_payload(authoritative_handoff),
    }
    return hashlib.sha256(stable_json(basis).encode("utf-8")).hexdigest()


def _matched_prompt_payload(run_state: dict[str, Any], role: str) -> dict[str, Any] | None:
    payload = run_state.get("pending_human_prompt")
    if not isinstance(payload, dict):
        return None
    target = payload.get("target")
    if target not in PROMPT_TARGET_VALUES:
        return None
    if target == "next_actual_agent" or target == role:
        return {
            "target": target,
            "text": payload.get("text", ""),
            "created_at": payload.get("created_at"),
            "created_by": payload.get("created_by"),
            "prompt_sha256": payload.get("prompt_sha256"),
        }
    return None


def backfill_loop_state(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    payload = dict(data)
    changed = False
    if "big_round_id" not in payload or not isinstance(payload.get("big_round_id"), str) or not payload.get("big_round_id"):
        payload["big_round_id"] = new_big_round_id()
        changed = True
    if "window_role" not in payload or payload.get("window_role") not in ROLE_VALUES:
        payload["window_role"] = payload.get("last_prompt_role") if payload.get("last_prompt_role") in ROLE_VALUES else "reader"
        changed = True
    if "role_window_id" not in payload or not isinstance(payload.get("role_window_id"), str) or not payload.get("role_window_id"):
        payload["role_window_id"] = new_role_window_id(str(payload["window_role"]))
        changed = True
    if "resume_budget" not in payload or not isinstance(payload.get("resume_budget"), int) or int(payload.get("resume_budget", 0)) <= 0:
        payload["resume_budget"] = 3
        changed = True
    if "resume_count" not in payload or not isinstance(payload.get("resume_count"), int) or int(payload.get("resume_count", 0)) < 0:
        payload["resume_count"] = 0
        changed = True
    for field in ["last_authoritative_handoff_path", "last_rollover_at", "last_rollover_reason"]:
        if field not in payload:
            payload[field] = None
            changed = True
    return payload, changed


def resolve_human_prompt_for_role(run_state: dict[str, Any], role: str) -> dict[str, Any] | None:
    require_enum(role, ROLE_VALUES, "role")
    return _matched_prompt_payload(run_state, role)


def sanitize_run_state_for_role(run_state: dict[str, Any], role: str) -> dict[str, Any]:
    require_enum(role, ROLE_VALUES, "role")
    sanitized = dict(run_state)
    pending = run_state.get("pending_human_prompt")
    if pending is not None:
        sanitized.pop("pending_human_prompt", None)
        matched_payload = _matched_prompt_payload(run_state, role)
        if matched_payload:
            sanitized["applied_human_prompt"] = matched_payload
    return sanitized


def build_prompt_contract_assignment(run_state: dict[str, Any], role: str) -> dict[str, Any]:
    sanitized = sanitize_run_state_for_role(run_state, role)
    sanitized.pop("updated_at", None)
    sanitized.pop("agent_program_ref", None)
    sanitized.pop("observability_segment_id", None)
    sanitized.pop("observability_sidecar_path", None)
    last_applied = sanitized.get("last_applied_human_prompt")
    if isinstance(last_applied, dict):
        stripped = dict(last_applied)
        stripped.pop("applied_at", None)
        sanitized["last_applied_human_prompt"] = stripped
    return sanitized


def build_canonical_contract_assignment(assignment_payload: dict[str, Any], role: str) -> dict[str, Any]:
    canonical = dict(assignment_payload)
    canonical.pop("updated_at", None)
    canonical.pop("agent_program_ref", None)
    canonical.pop("observability_segment_id", None)
    canonical.pop("observability_sidecar_path", None)
    pending = canonical.get("pending_human_prompt")
    if isinstance(pending, dict):
        stripped = dict(pending)
        stripped.pop("applied_at", None)
        canonical["pending_human_prompt"] = stripped
    return canonical


def build_prompt_render_state(run_state: dict[str, Any], role: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    sanitized = sanitize_run_state_for_role(run_state, role)
    return sanitized, sanitized.get("applied_human_prompt")


def compute_rendered_prompt_contract_hash(person_program: str, agent_program: str, role: str, run_state: dict[str, Any] | None, authoritative_handoff: dict[str, Any] | None = None) -> str:
    require_enum(role, ROLE_VALUES, "role")
    basis = {
        "person_program": person_program,
        "agent_program": agent_program,
        "role": role,
        "assignment": build_prompt_contract_assignment(run_state or {}, role),
        "authoritative_handoff": normalize_authoritative_handoff_payload(authoritative_handoff),
    }
    return hashlib.sha256(stable_json(basis).encode("utf-8")).hexdigest()


def validate_loop_state(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported loop state schema_version")
    data, _ = backfill_loop_state(data)
    for field in ["next_agent", "remaining_global_budget", "last_transition_reason", "last_resume_mode", "updated_at"]:
        if field not in data:
            raise ValueError(f"missing {field}")
    require_enum(data.get("next_agent"), ROLE_VALUES, "next_agent")
    require_enum(data.get("last_resume_mode"), RESUME_MODE_VALUES, "last_resume_mode")
    last_watch = data.get("last_watch_status")
    if last_watch is not None:
        require_enum(last_watch, WATCH_STATUS_VALUES, "last_watch_status")
    if not isinstance(data["remaining_global_budget"], dict):
        raise ValueError("missing remaining_global_budget")
    require_enum(data.get("window_role"), ROLE_VALUES, "window_role")
    if not isinstance(data.get("big_round_id"), str) or not data.get("big_round_id"):
        raise ValueError("big_round_id must be a non-empty string")
    if not isinstance(data.get("role_window_id"), str) or not data.get("role_window_id"):
        raise ValueError("role_window_id must be a non-empty string")
    if not isinstance(data.get("resume_budget"), int) or int(data.get("resume_budget", 0)) <= 0:
        raise ValueError("resume_budget must be a positive integer")
    if not isinstance(data.get("resume_count"), int) or int(data.get("resume_count", 0)) < 0:
        raise ValueError("resume_count must be a non-negative integer")
    handoff_path = data.get("last_authoritative_handoff_path")
    if handoff_path is not None and (not isinstance(handoff_path, str) or not handoff_path.strip()):
        raise ValueError("last_authoritative_handoff_path must be a non-empty string or null")
    return data


def validate_watch_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported watch snapshot schema_version")
    for field in ["assignment_id", "watch_status", "runner_active", "supervisor_polling", "remote_screen_names", "remote_jsons", "local_evidence_paths", "updated_at"]:
        if field not in data:
            raise ValueError(f"missing {field}")
    require_enum(data.get("watch_status"), WATCH_STATUS_VALUES, "watch_status")
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


def validate_run_state(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported run state schema_version")
    required = [
        "phase",
        "role_context_mode",
        "current_objective",
        "agent_program_ref",
        "reader_iteration",
        "reader_iteration_cap",
        "runner_iteration",
        "runner_iteration_cap",
        "success_condition",
        "remote_status",
        "last_result_summary",
        "next_action",
        "repair_count",
        "updated_at",
    ]
    for field in required:
        if field not in data:
            raise ValueError(f"missing {field}")
    require_enum(data.get("phase"), RUN_PHASE_VALUES, "phase")
    if data.get("role_context_mode") != "isolated":
        raise ValueError("run_state.role_context_mode must be 'isolated'")
    pending = data.get("pending_human_prompt")
    if pending is not None:
        if not isinstance(pending, dict):
            raise ValueError("pending_human_prompt must be a dict or null")
        require_enum(pending.get("target"), PROMPT_TARGET_VALUES, "pending_human_prompt.target")
        if not isinstance(pending.get("text"), str) or not pending.get("text").strip():
            raise ValueError("pending_human_prompt.text must be a non-empty string")
    return data


def load_run_state(path: Path) -> dict[str, Any]:
    return validate_run_state(read_json(path))


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


def load_agent_observability(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_agent_observability()
    payload = read_json(path)
    if "schema_version" not in payload:
        payload["schema_version"] = SCHEMA_VERSION
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported agent observability schema_version")
    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise ValueError("agent observability segments must be a list")
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError("observability segment must be a dict")
        if "merge_status" in segment:
            require_enum(segment.get("merge_status"), OBSERVABILITY_MERGE_STATUS_VALUES, "observability.merge_status")
    return payload


def upsert_observability_segment(path: Path, segment_payload: dict[str, Any]) -> dict[str, Any]:
    payload = load_agent_observability(path)
    segment_id = segment_payload.get("segment_id")
    if not isinstance(segment_id, str) or not segment_id:
        raise ValueError("segment_id must be a non-empty string")
    segments = payload.setdefault("segments", [])
    updated = False
    for index, existing in enumerate(segments):
        if existing.get("segment_id") == segment_id:
            merged = dict(existing)
            merged.update(segment_payload)
            segments[index] = merged
            updated = True
            break
    if not updated:
        segments.append(dict(segment_payload))
    payload["updated_at"] = now_utc_iso()
    atomic_write_json(path, payload)
    return payload


def merge_observability_sidecar(path: Path, segment_payload: dict[str, Any], sidecar_path: Path) -> dict[str, Any]:
    merged_segment = dict(segment_payload)
    merged_segment["sidecar_path"] = str(sidecar_path)
    if not sidecar_path.exists():
        merged_segment["merge_status"] = "not_found"
        return upsert_observability_segment(path, merged_segment)
    try:
        sidecar = read_json(sidecar_path)
        required = ["segment_id", "role", "task", "started_at", "expected_output", "why", "status", "updated_at"]
        for field in required:
            if field not in sidecar:
                raise ValueError(f"missing {field}")
        merged_segment.update({
            "task": sidecar["task"],
            "started_at": sidecar["started_at"],
            "expected_output": sidecar["expected_output"],
            "why": sidecar["why"],
            "status": sidecar["status"],
        })
        if "eta" in sidecar:
            merged_segment["eta"] = sidecar["eta"]
        if "ended_at" in sidecar:
            merged_segment["ended_at"] = sidecar["ended_at"]
        if "completion_summary" in sidecar:
            merged_segment["completion_summary"] = sidecar["completion_summary"]
        if "status_note" in sidecar:
            merged_segment["status_note"] = sidecar["status_note"]
        merged_segment["merge_status"] = "merged"
    except Exception as exc:
        merged_segment["merge_status"] = "invalid_sidecar"
        merged_segment["merge_error"] = str(exc)
    return upsert_observability_segment(path, merged_segment)


def overlay_observability_sidecars(payload: dict[str, Any]) -> dict[str, Any]:
    hydrated = dict(payload)
    segments = []
    for segment in hydrated.get("segments", []):
        merged_segment = dict(segment)
        sidecar_path_raw = merged_segment.get("sidecar_path")
        if sidecar_path_raw:
            sidecar_path = Path(str(sidecar_path_raw))
            if sidecar_path.exists():
                try:
                    sidecar = read_json(sidecar_path)
                except Exception:
                    sidecar = None
                if isinstance(sidecar, dict) and sidecar.get("segment_id") == merged_segment.get("segment_id"):
                    for field in [
                        "task",
                        "started_at",
                        "ended_at",
                        "eta",
                        "expected_output",
                        "why",
                        "status",
                        "completion_summary",
                        "status_note",
                        "updated_at",
                    ]:
                        if field in sidecar:
                            merged_segment[field] = sidecar[field]
        segments.append(merged_segment)
    hydrated["segments"] = segments
    return hydrated


def write_pending_human_prompt(path: Path, *, target: str, text: str, created_by: str = "dashboard") -> dict[str, Any]:
    payload = load_run_state(path)
    prompt = {
        "target": target,
        "text": text.strip(),
        "created_at": now_utc_iso(),
        "created_by": created_by,
        "prompt_sha256": text_sha256(text.strip()),
    }
    payload["pending_human_prompt"] = prompt
    payload["updated_at"] = now_utc_iso()
    validate_run_state(payload)
    atomic_write_json(path, payload)
    return payload


def _default_agent_program_text() -> str:
    return DEFAULT_AGENT_PROGRAM


def ensure_role_surfaces(paths: ArtifactPaths) -> None:
    for role_name, surface in DEFAULT_ROLE_SURFACES.items():
        role_root = paths.reader_role_root if role_name == "reader" else paths.runner_role_root
        role_root.mkdir(parents=True, exist_ok=True)
        agent_path = role_root / "AGENTS.md"
        if not agent_path.exists():
            atomic_write_text(agent_path, surface["agents"])
        skills = surface.get("skills")
        if skills is None and "skill_name" in surface and "skill" in surface:
            skills = {surface["skill_name"]: surface["skill"]}
        for skill_name, skill_body in (skills or {}).items():
            skill_root = role_root / "skills" / str(skill_name)
            skill_root.mkdir(parents=True, exist_ok=True)
            skill_path = skill_root / "SKILL.md"
            if not skill_path.exists():
                atomic_write_text(skill_path, skill_body)


def export_omx_compat_artifacts(paths: ArtifactPaths, config: dict[str, Any] | None = None) -> None:
    runtime = (config or {}).get("runtime", {}) if isinstance(config, dict) else {}
    if not bool(runtime.get("compat_omx_export", False)):
        return
    compat_state = paths.omx_compat_root / "state"
    compat_logs = paths.omx_compat_root / "logs"
    compat_state.mkdir(parents=True, exist_ok=True)
    compat_logs.mkdir(parents=True, exist_ok=True)
    for source, target in [
        (paths.loop_state, compat_state / "research_loop_state.json"),
        (paths.watch_snapshot, compat_state / "research_watch_snapshot.json"),
        (paths.watch_events, compat_state / "research_watch_events.jsonl"),
        (paths.run_state, compat_state / "run-state.json"),
        (paths.agent_observability, compat_state / "agent-observability.json"),
        (paths.ai_worklog, compat_logs / "ai-worklog.md"),
    ]:
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def import_legacy_omx_state(paths: ArtifactPaths, config: dict[str, Any] | None = None) -> None:
    if str(paths.runtime_root.name) == ".omx":
        return
    legacy_roots = [paths.legacy_runtime_root, paths.omx_compat_root]
    for legacy_root in legacy_roots:
        legacy_state = legacy_root / "state"
        legacy_logs = legacy_root / "logs"
        for source, target in [
            (legacy_state / "research_loop_state.json", paths.loop_state),
            (legacy_state / "research_watch_snapshot.json", paths.watch_snapshot),
            (legacy_state / "research_watch_events.jsonl", paths.watch_events),
            (legacy_state / "run-state.json", paths.run_state),
            (legacy_state / "agent-observability.json", paths.agent_observability),
            (legacy_logs / "ai-worklog.md", paths.ai_worklog),
        ]:
            if not target.exists() and source.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def ensure_program_files(root: Path, config: dict[str, Any] | None = None, *, allow_bootstrap_agent: bool = True) -> ArtifactPaths:
    paths = resolve_artifact_paths(root, config)
    ensure_role_surfaces(paths)
    paths.workspace_root.mkdir(parents=True, exist_ok=True)
    if not paths.person_program.exists():
        raise FileNotFoundError("Missing person_program.md. Create it before starting the sub-PHD runtime loop.")
    read_validated_text(paths.person_program, "person_program")
    if not paths.agent_program.exists():
        if not allow_bootstrap_agent:
            raise FileNotFoundError("Missing agent_program.md. Start via autoloop to bootstrap it, or restore it from version control.")
        atomic_write_text(paths.agent_program, _default_agent_program_text())
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
    else:
        try:
            read_validated_text(paths.agent_program, "agent_program")
        except Exception:
            if not allow_bootstrap_agent:
                raise
            atomic_write_text(paths.agent_program, _default_agent_program_text())
            append_jsonl(
                paths.watch_events,
                event_payload(
                    event_type="restore_agent_program",
                    source="autoloop",
                    reason="corrupted_agent_program_restored_from_seed",
                    assignment_id=None,
                    run_id=None,
                    watch_status="idle",
                ),
            )
    return paths


def require_runtime_artifacts(root: Path, config: dict[str, Any] | None = None) -> ArtifactPaths:
    paths = ensure_program_files(root, config, allow_bootstrap_agent=False)
    missing = [str(p) for p in [paths.run_state] if not p.exists()]
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
    import_legacy_omx_state(paths, config)
    if not paths.loop_state.exists():
        atomic_write_json(paths.loop_state, default_loop_state(config))
    else:
        raw_loop_state = read_json(paths.loop_state)
        migrated_loop_state = validate_loop_state(raw_loop_state)
        if migrated_loop_state != raw_loop_state:
            atomic_write_json(paths.loop_state, migrated_loop_state)
    if not paths.watch_snapshot.exists():
        atomic_write_json(paths.watch_snapshot, default_watch_snapshot())
    if not paths.watch_events.exists():
        paths.watch_events.parent.mkdir(parents=True, exist_ok=True)
        paths.watch_events.touch()
    if not paths.run_state.exists():
        atomic_write_json(paths.run_state, default_run_state(config))
    if not paths.agent_observability.exists():
        atomic_write_json(paths.agent_observability, default_agent_observability())
    export_omx_compat_artifacts(paths, config)
    return paths


def reset_runtime_state(paths: ArtifactPaths, config: dict[str, Any] | None = None, *, reason: str = "fresh_task_start") -> dict[str, Any]:
    loop_state = default_loop_state(config)
    loop_state["last_transition_reason"] = reason
    loop_state["window_role"] = "reader"
    loop_state["role_window_id"] = new_role_window_id("reader")
    loop_state["resume_count"] = 0
    loop_state["last_authoritative_handoff_path"] = None
    loop_state["last_rollover_at"] = None
    loop_state["last_rollover_reason"] = None
    loop_state["updated_at"] = now_utc_iso()
    watch_snapshot = default_watch_snapshot()
    watch_snapshot["updated_at"] = now_utc_iso()
    run_state = default_run_state(config)
    run_state["updated_at"] = now_utc_iso()
    observability = default_agent_observability()
    observability["updated_at"] = now_utc_iso()
    atomic_write_json(paths.loop_state, loop_state)
    atomic_write_json(paths.watch_snapshot, watch_snapshot)
    atomic_write_json(paths.run_state, run_state)
    atomic_write_json(paths.agent_observability, observability)
    export_omx_compat_artifacts(paths, config)
    return run_state


def load_loop_state(path: Path) -> dict[str, Any]:
    return validate_loop_state(read_json(path))


def load_watch_snapshot(path: Path) -> dict[str, Any]:
    return validate_watch_snapshot(read_json(path))


def validate_resume_request(*, loop_state: dict[str, Any], role: str, resume_mode: str, prompt_contract_hash: str) -> None:
    require_enum(role, ROLE_VALUES, "role")
    require_enum(resume_mode, RESUME_MODE_VALUES, "resume_mode")
    if resume_mode == "fresh":
        return
    if loop_state.get("last_prompt_role") != role:
        raise ValueError("cross-role resume is forbidden")
    if loop_state.get("prompt_contract_hash") != prompt_contract_hash:
        raise ValueError("resume prompt hash mismatch")


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
