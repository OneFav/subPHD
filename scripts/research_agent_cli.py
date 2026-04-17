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
import shlex
import shutil
import subprocess
import time
from typing import Any

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

from scripts.research_loop_contract import (
    ROLE_VALUES,
    RESUME_MODE_VALUES,
    append_ai_worklog_entry,
    compact_text_summary,
    compute_rendered_prompt_contract_hash,
    render_compact_summary,
    require_runtime_artifacts,
    compute_prompt_contract_hash,
    export_omx_compat_artifacts,
    load_loop_state,
    load_run_state,
    merge_observability_sidecar,
    now_utc_iso,
    read_validated_text,
    sanitize_run_state_for_role,
    text_sha256,
    upsert_observability_segment,
    validate_resume_request,
)

DEFAULT_ROLE_NOTES = {
    "reader": (
        "You are the READER lane. Do deep review/research only. "
        "You may directly update agent_program.md and must write a deep, structured assignment for runner."
    ),
    "runner": (
        "You are the RUNNER lane. You may implement or modify local code within the assignment bounds. "
        "Smoke and formal experiments remain remote-only. "
        "You may autonomously iterate only within the current assignment bounds."
    ),
}

def load_project_config(root: Path) -> dict[str, Any]:
    config_path = root / "research_agent.toml"
    if tomllib is None or not config_path.exists():
        return {}
    with config_path.open("rb") as f:
        return tomllib.load(f)


def build_supervisor_template(paths_or_root, poll_seconds: int, config: dict[str, Any]) -> str:
    if hasattr(paths_or_root, "synced_results_root"):
        paths = paths_or_root
    else:
        root = Path(paths_or_root)
        from scripts.research_loop_contract import resolve_artifact_paths
        paths = resolve_artifact_paths(root, config)
    remote = config.get("remote", {}) if isinstance(config, dict) else {}
    ssh_key = remote.get("ssh_key") or "<ssh-key>"
    host = remote.get("host") or "<remote-host>"
    port = remote.get("port", 22)
    remote_code_dir = remote.get("remote_code_dir") or "<remote-code-dir>"
    remote_result_dir = remote.get("remote_result_dir") or "<remote-result-dir>"
    local_result_dir = str(paths.synced_results_root)
    return (
        "Canonical remote launch (write a UTF-8 bash script locally, then launch it safely):\n"
        "python scripts/research_supervisor.py launch-bash "
        f"--ssh-key {ssh_key} "
        f"--host {host} "
        f"--port {port} "
        f"--remote-workdir {remote_code_dir} "
        "--script-file <local-bash-script>\n\n"
        "Canonical remote watch:\n"
        "python scripts/research_supervisor.py watch "
        f"--ssh-key {ssh_key} "
        f"--host {host} "
        f"--port {port} "
        "--screen-prefix <run-id> "
        f"--remote-result-dir {remote_result_dir} "
        f"--local-result-dir {local_result_dir} "
        "--local-glob \"*.json\" "
        f"--poll-seconds {poll_seconds} "
        "--max-polls 120 "
        f"--snapshot-path {paths.watch_snapshot} "
        f"--event-log-path {paths.watch_events}"
    )


def ensure_runner_remote_requirements(config: dict[str, Any]) -> None:
    remote = config.get("remote", {}) if isinstance(config, dict) else {}
    required = ["ssh_key", "host", "port", "remote_code_dir", "remote_result_dir"]
    missing = [name for name in required if not remote.get(name)]
    if missing:
        raise ValueError(f"runner mode requires remote config keys: {', '.join(missing)}")


def load_role_surface(role_root: Path) -> str:
    parts: list[str] = []
    agents_path = role_root / "AGENTS.md"
    if agents_path.exists():
        parts.append(f"Role AGENTS ({agents_path}):\n{agents_path.read_text(encoding='utf-8')}")
    skills_root = role_root / "skills"
    if skills_root.exists():
        for skill_path in sorted(skills_root.glob("*/SKILL.md")):
            parts.append(f"Role skill ({skill_path}):\n{skill_path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts).strip()


def build_runtime_whitelist(paths) -> list[str]:
    return [
        str(paths.person_program),
        str(paths.agent_program),
        str(paths.run_state),
        str(paths.ai_worklog),
        str(paths.reports_root / "*"),
        str(paths.synced_results_root / "*"),
        str(paths.workspace_root),
    ]


def build_role_prompt(
    *,
    role: str,
    paths=None,
    person_program: str,
    agent_program: str,
    person_program_full: str,
    agent_program_full: str,
    run_state: dict[str, Any],
    poll_seconds: int,
    report_path: str,
    supervisor_template: str,
    legacy_task: str | None = None,
) -> str:
    role = role.strip().lower()
    if role not in ROLE_VALUES:
        raise ValueError(f"Unknown role: {role}")
    if paths is None:
        from scripts.research_loop_contract import resolve_artifact_paths
        paths = resolve_artifact_paths(ROOT_DIR, load_project_config(ROOT_DIR))
    legacy_block = f"\nLegacy request context:\n{legacy_task}\n" if legacy_task else ""
    role_root = paths.reader_role_root if role == "reader" else paths.runner_role_root
    role_surface_block = load_role_surface(role_root)
    extra_role_rules = ""
    if role == "reader":
        whitelist = "\n".join(f"  - {item}" for item in build_runtime_whitelist(paths))
        extra_role_rules = (
            "\nReader read whitelist:\n"
            f"{whitelist}\n"
            "- Stay inside this whitelist first; only broaden reads when the current step cannot be completed from these files.\n"
            "- At the end of the reader turn, hardcode `run-state.json` to hand off to `runner` by setting:\n"
            "  - `phase = \"runner\"`\n"
            "  - `next_action = \"runner\"`\n"
        )
    else:
        extra_role_rules = (
            "\nRunner-owned state transition:\n"
            "- You may implement or modify local code first when the assignment requires missing code, boundary fixes, or local scaffold work.\n"
            "- Smoke and formal experiments remain remote-only; do not run local training or local formal experiment loops.\n"
            "- Before finishing a remote run, prune `remote_result_dir`: delete bulky intermediate or process files that do not need to be synced back.\n"
            "- Leave only the compact core result set needed locally (for example decision, metrics, summary, manifest, and other explicitly needed artifacts).\n"
            "- If a large artifact might matter later, summarize it in a small retained file instead of leaving the full bulky file in `remote_result_dir` by default.\n"
            "- You own the post-run state change.\n"
            "- If the experiment is judged successful, or `runner_iteration` has reached `runner_iteration_cap`, set `run-state.json` back to `reader`.\n"
            "- Otherwise, set the next state needed for execution continuation (typically `watch` after a remote launch).\n"
        )
    applied_prompt = run_state.get("applied_human_prompt")
    prompt_block = ""
    if isinstance(applied_prompt, dict) and applied_prompt.get("text"):
        prompt_block = (
            "\nONE-TIME HUMAN PROMPT FOR THIS INVOCATION:\n"
            f"- Target: {applied_prompt.get('target')}\n"
            f"- Instruction: {applied_prompt.get('text')}\n"
            "- This instruction is one-shot and applies only to the current invocation.\n"
        )
    observability_block = ""
    sidecar_path = run_state.get("observability_sidecar_path")
    segment_id = run_state.get("observability_segment_id")
    if sidecar_path and segment_id:
        observability_block = (
            "\nObservability JSON sidecar:\n"
            f"- Segment id: {segment_id}\n"
            f"- Write/update JSON at: `{sidecar_path}`\n"
            "- Write/update JSON twice for this invocation.\n"
            "- Write #1 immediately at start with: segment_id, role, task, started_at, why, expected_output, status='running', updated_at.\n"
            "- Write #2 before exit to update the same JSON with: status, completion_summary, ended_at, updated_at. Keep the start fields intact.\n"
            "- Optional field: eta. Optional field: status_note.\n"
            "- Use plain language that a human can understand quickly.\n"
            "- Do not write vague filler such as 'the process requires this', 'advance the workflow', 'complete the current stage', or other template-like explanations.\n"
            "- For `expected_output`, name the concrete experiment, code change, check, artifact, file, or decision the human will get from this turn.\n"
            "- For `why`, name the concrete problem, risk, uncertainty, or decision this step is trying to resolve.\n"
            "- Be specific: if this is an experiment, say which experiment; if this is a metric check, say which metric; if this is a file/report, say which file/report.\n"
            "- If you use a technical term or a new abbreviation, explain it in ordinary words immediately.\n"
            "- Keep `expected_output` and `why` to one or two short sentences each, but make them concrete and readable.\n"
        )
    return f"""$ralph role={role} execute the current research loop step.

ROLE NOTE:
{DEFAULT_ROLE_NOTES[role]}

PERSON PROGRAM (human-owned):
{person_program_full}

AGENT PROGRAM (reader-writable):
{agent_program_full}

CURRENT RUN STATE:
{json.dumps(run_state, ensure_ascii=False, indent=2)}
{legacy_block}
Execution requirements:
- Use the role contract above; do not violate artifact ownership.
- Reader owns semantic handoff authoring and may edit `agent_program.md`.
- Runner may implement or modify local code, but smoke and formal experiments remain remote-only.
- Reader and runner are context-isolated; continue work from artifacts, not from shared conversational memory.
- Program sources are intentionally compact in this prompt; use the file paths + hashes below and read the files from disk when needed.
- Use `scripts/research_supervisor.py watch` for long-running remote monitoring rather than rediscovering active runs repeatedly.
- Poll cadence reference: every {poll_seconds} seconds.
- Write final role summary to: `{report_path}`.
{extra_role_rules}
{prompt_block}
{observability_block}

Project-local role surface:
{role_surface_block or '(No additional role surface files found)'}

Role launch contract:
- role_name = `{role}`
- role_surface_root = `{role_root}`
- shared_control_root = `{paths.person_program.parent}`
- shared_workspace_root = `{paths.workspace_root}`
- canonical_runtime_root = `{paths.runtime_root}`

Program summaries (for compact operational logging / quick reference):
{person_program}
{agent_program}

Supervisor template:
{supervisor_template}
"""


def build_codex_command(
    *,
    workspace_root: str | None = None,
    role_surface_root: str | None = None,
    output_file: str,
    resume_mode: str,
    model: str | None,
    profile: str | None,
    yolo: bool,
    workdir: str | None = None,
    prompt_file: str | None = None,
) -> list[str]:
    if resume_mode not in RESUME_MODE_VALUES:
        raise ValueError(f"Unknown resume mode: {resume_mode}")
    effective_workspace_root = workspace_root or workdir or "."
    effective_role_surface_root = role_surface_root or workdir or "."
    cmd = ["codex", "exec", "--cd", effective_role_surface_root, "--add-dir", effective_workspace_root, "--skip-git-repo-check"]
    if yolo:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        cmd.extend(["-s", "danger-full-access"])
    if model:
        cmd.extend(["-m", model])
    if profile:
        cmd.extend(["-p", profile])
    cmd.extend(["-o", output_file])
    if resume_mode == "resume_same_role":
        cmd.extend(["resume", "--last"])
    cmd.append("-")
    return cmd


def resolve_launcher_path(name: str) -> str:
    candidates = [f"{name}.cmd", name, f"{name}.ps1"]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return name


def write_prompt_file(prompt_dir: Path, prompt_text: str) -> Path:
    prompt_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    prompt_file = prompt_dir / f"research-agent-{stamp}.md"
    prompt_file.write_text(prompt_text, encoding="utf-8")
    return prompt_file


def write_command_file(command_dir: Path, cmd: list[str]) -> Path:
    command_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    path = command_dir / f"research-agent-{stamp}.cmd.txt"
    path.write_text(" ".join(shlex.quote(part) for part in cmd), encoding="utf-8")
    return path


def write_launch_metadata(
    metadata_path: Path,
    *,
    role: str,
    role_surface_root: Path | None = None,
    rendered_prompt_hash: str,
    prompt_file: Path,
    command_file: Path,
    report_file: Path,
    canonical_state_hash: str | None = None,
    applied_prompt_hash: str | None = None,
    prompt_applied: bool = False,
    observability_sidecar: Path | None = None,
    segment_id: str | None = None,
) -> Path:
    from scripts.research_loop_contract import atomic_write_json
    if metadata_path.suffix.lower() != ".json":
        metadata_path = metadata_path / ".omx" / "last-launch-metadata.json"
    payload = {
        "role": role,
        "prompt_contract_hash": rendered_prompt_hash,
        "rendered_prompt_hash": rendered_prompt_hash,
        "canonical_state_hash": canonical_state_hash,
        "applied_prompt_hash": applied_prompt_hash,
        "prompt_applied": prompt_applied,
        "role_surface_root": str(role_surface_root) if role_surface_root else None,
        "prompt_file": str(prompt_file),
        "command_file": str(command_file),
        "report_file": str(report_file),
        "observability_sidecar": str(observability_sidecar) if observability_sidecar else None,
        "segment_id": segment_id,
        "canonical_transport_marker": "scripts/research_supervisor.py launch-bash",
        "canonical_watch_marker": "scripts/research_supervisor.py watch",
        "updated_at": now_utc_iso(),
    }
    atomic_write_json(metadata_path, payload)
    return metadata_path


def normalize_post_role_run_state(role: str, run_state: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(run_state)
    if role == "reader":
        normalized["phase"] = "runner"
        normalized["next_action"] = "runner"
        return normalized

    success_statuses = {"success", "complete", "smoke_complete"}
    if (
        normalized.get("phase") == "reader"
        or normalized.get("next_action") == "reader"
        or normalized.get("remote_status") in success_statuses
        or int(normalized.get("runner_iteration", 0)) >= int(normalized.get("runner_iteration_cap", 0))
    ):
        normalized["phase"] = "reader"
        normalized["next_action"] = "reader"
    return normalized


def prepare_prompt_contract(*, role: str, person_program_text: str, agent_program_text: str, run_state: dict[str, Any]) -> dict[str, Any]:
    render_state = sanitize_run_state_for_role(run_state, role)
    applied_prompt = render_state.get("applied_human_prompt")
    return {
        "canonical_state_hash": compute_prompt_contract_hash(person_program_text, agent_program_text, role, run_state),
        "rendered_prompt_hash": compute_rendered_prompt_contract_hash(person_program_text, agent_program_text, role, run_state),
        "render_state": render_state,
        "applied_prompt": applied_prompt,
        "applied_prompt_hash": (applied_prompt or {}).get("prompt_sha256"),
    }


def consume_pending_human_prompt_if_matched(run_state: dict[str, Any], *, matched_prompt: dict[str, Any] | None) -> dict[str, Any]:
    next_state = dict(run_state)
    if not matched_prompt:
        return next_state
    next_state.pop("pending_human_prompt", None)
    next_state["last_applied_human_prompt"] = {
        "target": matched_prompt.get("target"),
        "text": matched_prompt.get("text"),
        "applied_at": now_utc_iso(),
    }
    return next_state


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Role-aware launcher for the sub-PHD runtime via codex exec / Ralph.")
    ap.add_argument("--task")
    ap.add_argument("--workdir", default=".")
    ap.add_argument("--role", choices=sorted(ROLE_VALUES))
    ap.add_argument("--resume-mode", choices=sorted(RESUME_MODE_VALUES), default="fresh")
    ap.add_argument("--expected-prompt-contract-hash")
    ap.add_argument("--poll-seconds", type=int)
    ap.add_argument("--model")
    ap.add_argument("--profile")
    ap.add_argument("--no-yolo", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report-file")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.workdir).resolve()
    config = load_project_config(root)
    paths = require_runtime_artifacts(root, config)
    loop_state = load_loop_state(paths.loop_state)
    run_state = load_run_state(paths.run_state)
    role = args.role or run_state["phase"]
    role_surface_root = paths.reader_role_root if role == "reader" else paths.runner_role_root
    poll_seconds = int(args.poll_seconds) if args.poll_seconds is not None else int(config.get("default_poll_seconds", 300))
    model = args.model or config.get("default_model", "gpt-5.4")
    person_program_text = read_validated_text(paths.person_program, "person_program")
    agent_program_text = read_validated_text(paths.agent_program, "agent_program")
    if role == "runner" and not args.dry_run:
        ensure_runner_remote_requirements(config)
        if args.task:
            raise ValueError("runner mode rejects ad-hoc local task injection; use reader-produced artifacts only")
    prompt_contract = prepare_prompt_contract(
        role=role,
        person_program_text=person_program_text,
        agent_program_text=agent_program_text,
        run_state=run_state,
    )
    canonical_prompt_hash = prompt_contract["canonical_state_hash"]
    rendered_run_state = prompt_contract["render_state"]
    prompt_hash = prompt_contract["rendered_prompt_hash"]
    expected_hash = args.expected_prompt_contract_hash or prompt_hash
    if expected_hash != prompt_hash:
        raise ValueError("expected prompt contract hash mismatch")
    validate_resume_request(
        loop_state=loop_state,
        role=role,
        resume_mode=args.resume_mode,
        prompt_contract_hash=prompt_hash,
    )

    report_dir = paths.reports_root
    report_dir.mkdir(parents=True, exist_ok=True)
    default_report = report_dir / f"research-agent-report-{time.strftime('%Y%m%dT%H%M%S')}.md"
    report_file = Path(args.report_file).resolve() if args.report_file else default_report
    supervisor_template = build_supervisor_template(paths, poll_seconds, config)
    person_program_summary = render_compact_summary(
        compact_text_summary("person_program", paths.person_program, person_program_text)
    )
    agent_program_summary = render_compact_summary(
        compact_text_summary("agent_program", paths.agent_program, agent_program_text)
    )
    segment_id = f"{role}-{time.strftime('%Y%m%dT%H%M%S')}"
    sidecar_path = paths.reports_root / f"agent-observability-{segment_id}.json"
    rendered_run_state["observability_segment_id"] = segment_id
    rendered_run_state["observability_sidecar_path"] = str(sidecar_path)

    prompt_text = build_role_prompt(
        role=role,
        paths=paths,
        person_program=person_program_summary,
        agent_program=agent_program_summary,
        person_program_full=person_program_text,
        agent_program_full=agent_program_text,
        run_state=rendered_run_state,
        poll_seconds=poll_seconds,
        report_path=str(report_file),
        supervisor_template=supervisor_template,
        legacy_task=args.task,
    )
    prompt_file = write_prompt_file(paths.prompts_root, prompt_text)
    output_file = paths.last_agent_message
    output_file.parent.mkdir(parents=True, exist_ok=True)

    loop_state["last_prompt_role"] = role
    loop_state["last_prompt_path"] = str(prompt_file)
    loop_state["prompt_contract_hash"] = prompt_hash
    loop_state["updated_at"] = now_utc_iso()
    run_state["agent_program_ref"] = text_sha256(agent_program_text)
    run_state["updated_at"] = now_utc_iso()
    from scripts.research_loop_contract import atomic_write_json
    atomic_write_json(paths.loop_state, loop_state)
    atomic_write_json(paths.run_state, run_state)
    export_omx_compat_artifacts(paths, config)

    upsert_observability_segment(
        paths.agent_observability,
        {
            "segment_id": segment_id,
            "run_id": run_state.get("run_id"),
            "role": role,
            "status": "running",
            "started_at": now_utc_iso(),
            "sidecar_path": str(sidecar_path),
            "merge_status": "not_found",
        },
    )

    cmd = build_codex_command(
        workspace_root=str(root),
        role_surface_root=str(role_surface_root),
        output_file=str(output_file),
        resume_mode=args.resume_mode,
        model=model,
        profile=args.profile,
        yolo=not args.no_yolo,
    )
    cmd[0] = resolve_launcher_path(cmd[0])
    command_file = write_command_file(paths.commands_root, cmd)
    metadata_file = write_launch_metadata(
        paths.last_launch_metadata,
        role=role,
        role_surface_root=role_surface_root,
        rendered_prompt_hash=prompt_hash,
        prompt_file=prompt_file,
        command_file=command_file,
        report_file=report_file,
        canonical_state_hash=canonical_prompt_hash,
        applied_prompt_hash=prompt_contract["applied_prompt_hash"],
        prompt_applied=bool(prompt_contract["applied_prompt"]),
        observability_sidecar=sidecar_path,
        segment_id=segment_id,
    )

    if rendered_run_state.get("applied_human_prompt") and not args.dry_run:
        run_state = consume_pending_human_prompt_if_matched(
            run_state,
            matched_prompt=rendered_run_state.get("applied_human_prompt"),
        )
        run_state["last_applied_human_prompt"]["applied_role"] = role
        run_state["updated_at"] = now_utc_iso()
        atomic_write_json(paths.run_state, run_state)
        export_omx_compat_artifacts(paths, config)

    print("Launching research agent:")
    print(f"Role: {role}")
    print(f"Resume mode: {args.resume_mode}")
    print(f"Prompt hash: {prompt_hash}")
    print(f"Prompt file: {prompt_file}")
    print(f"Output file: {output_file}")
    print(f"Report file: {report_file}")
    print(f"Command file: {command_file}")
    print(f"Launch metadata file: {metadata_file}")

    if args.dry_run:
        return 0
    start_time = now_utc_iso()
    completed = subprocess.run(cmd, cwd=role_surface_root, input=prompt_text, text=True)
    merge_observability_sidecar(
        paths.agent_observability,
        {
            "segment_id": segment_id,
            "run_id": run_state.get("run_id"),
            "role": role,
            "status": "completed" if int(completed.returncode) == 0 else "failed",
            "started_at": start_time,
            "ended_at": now_utc_iso(),
        },
        sidecar_path,
    )
    try:
        latest_run_state = load_run_state(paths.run_state)
    except Exception:
        latest_run_state = run_state
    latest_run_state = normalize_post_role_run_state(role, latest_run_state)
    atomic_write_json(paths.run_state, latest_run_state)
    export_omx_compat_artifacts(paths, config)
    append_ai_worklog_entry(
        paths.ai_worklog,
        {
            "role": role,
            "start_time": start_time,
            "current_objective": latest_run_state.get("current_objective", ""),
            "runner_iteration": latest_run_state.get("runner_iteration", 0),
            "runner_iteration_cap": latest_run_state.get("runner_iteration_cap", 0),
            "reader_iteration": latest_run_state.get("reader_iteration", 0),
            "reader_iteration_cap": latest_run_state.get("reader_iteration_cap", 0),
            "success_condition": latest_run_state.get("success_condition", ""),
            "remote_status": latest_run_state.get("remote_status", ""),
            "latest_result_summary": latest_run_state.get("last_result_summary", ""),
            "next_action": latest_run_state.get("next_action", ""),
        },
    )
    export_omx_compat_artifacts(paths, config)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
