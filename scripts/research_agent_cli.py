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
import re
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
    compute_prompt_contract_hash,
    load_task_state,
    now_utc_iso,
    read_validated_text,
    render_compact_summary,
    require_runtime_artifacts,
    resolve_execution_backend,
    text_sha256,
)

DEFAULT_ROLE_NOTES = {
    "reader": (
        "You are the READER lane. Do deep review/research only. "
        "You may directly update agent_program.md and must write a deep, structured assignment for runner."
    ),
    "runner": (
        "You are the RUNNER lane. You may implement or modify local code within the assignment bounds. "
        "Experiment launch and watch behavior must follow the configured execution backend. "
        "You may autonomously iterate only within the current assignment bounds."
    ),
}

BASE_ROLE_SKILLS = {
    "reader": "reader-handoff",
    "runner": "runner-implementation",
}

ROLE_SKILL_KEYWORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "reader": {
        "experiment-plan": ("plan", "protocol", "run order", "roadmap", "ablation", "next experiment"),
        "analyze-results": ("analyze", "analysis", "compare", "comparison", "result", "metric", "delta", "table", "summary"),
        "result-to-claim": ("claim", "claims", "supported", "support", "evidence", "verdict", "judge", "decision"),
    },
    "runner": {
        "experiment-bridge": ("implement", "launch", "run", "remote", "deploy", "experiment", "calibration"),
        "monitor-experiment": ("watch", "monitor", "progress", "stalled", "heartbeat", "alive", "poll"),
        "training-check": ("training", "loss", "wandb", "nan", "diverge", "divergence", "flatline", "health"),
    },
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
    backend = resolve_execution_backend(config if isinstance(config, dict) else {})
    if backend == "local":
        local = config.get("local", {}) if isinstance(config, dict) else {}
        local_workdir = local.get("workdir") or "."
        local_result_dir = local.get("result_dir") or "results"
        local_log_dir = local.get("log_dir") or ".omx/logs/local-runs"
        local_pid_dir = local.get("pid_dir") or ".omx/state/local-runs"
        metadata_path = f"{local_pid_dir}/<run-id>.json"
        return (
            "Canonical local launch (write a UTF-8 command script locally, then launch it as a background process):\n"
            "python scripts/research_supervisor.py launch "
            "--backend local "
            f"--local-workdir {local_workdir} "
            f"--local-result-dir {local_result_dir} "
            f"--local-log-dir {local_log_dir} "
            f"--local-pid-dir {local_pid_dir} "
            "--run-id <run-id> "
            "--script-file <local-command-script>\n\n"
            "Canonical local watch:\n"
            "python scripts/research_supervisor.py watch-backend "
            "--backend local "
            f"--local-metadata-path {metadata_path} "
            f"--local-result-dir {local_result_dir} "
            "--local-glob \"*.json\" "
            f"--poll-seconds {poll_seconds} "
            "--max-polls 120 "
            f"--snapshot-path {paths.watch_snapshot} "
            f"--event-log-path {paths.watch_events}"
        )
    remote = config.get("remote", {}) if isinstance(config, dict) else {}
    ssh_key = remote.get("ssh_key") or "C:/Users/admin/Desktop/insightnet-codex/package/.subphd/keys/autoresearch_ed25519"
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


def ensure_runner_backend_requirements(config: dict[str, Any]) -> None:
    backend = resolve_execution_backend(config)
    if backend == "ssh":
        ensure_runner_remote_requirements(config)
        return
    local = config.get("local", {}) if isinstance(config, dict) else {}
    if local is not None and not isinstance(local, dict):
        raise ValueError("local config must be a table when execution.backend is local")


def parse_role_skill_hints(agent_program_text: str, role: str) -> set[str]:
    if not agent_program_text:
        return set()
    pattern = re.compile(
        rf"(?im)^(?:active\s+skills|{re.escape(role)}\s+skills|active\s+{re.escape(role)}\s+skills)\s*:\s*(.+)$"
    )
    matches = pattern.findall(agent_program_text)
    selected: set[str] = set()
    for match in matches:
        for token in re.split(r"[,\|/]+", match):
            normalized = token.strip().lower()
            if normalized:
                selected.add(normalized)
    return selected


def select_role_skills(role: str, task_state: dict[str, Any], agent_program_text: str, execution_backend: str | None = None) -> list[str]:
    selected = {BASE_ROLE_SKILLS[role]}
    if role == "runner":
        backend = execution_backend or task_state.get("execution_backend")
        if backend == "local":
            selected.update({"local-experiment", "local-watch"})
        elif backend == "ssh":
            selected.update({"experiment-bridge", "monitor-experiment"})
    explicit = task_state.get("active_role_skills")
    if isinstance(explicit, dict):
        explicit = explicit.get(role)
    if isinstance(explicit, list):
        selected.update(str(item).strip().lower() for item in explicit if str(item).strip())
    elif isinstance(explicit, str) and explicit.strip():
        selected.add(explicit.strip().lower())
    selected.update(parse_role_skill_hints(agent_program_text, role))

    context_parts = [agent_program_text]
    for key in ("current_objective", "next_action", "success_condition", "remote_status"):
        value = task_state.get(key)
        if isinstance(value, str):
            context_parts.append(value)
    pending_prompt = task_state.get("applied_human_prompt") or task_state.get("pending_human_prompt")
    if isinstance(pending_prompt, dict):
        prompt_text = pending_prompt.get("text")
        if isinstance(prompt_text, str):
            context_parts.append(prompt_text)
    context = " ".join(context_parts).lower()
    backend = execution_backend or task_state.get("execution_backend")
    for skill_name, keywords in ROLE_SKILL_KEYWORDS.get(role, {}).items():
        if role == "runner" and backend == "local" and skill_name in {"experiment-bridge", "monitor-experiment"}:
            continue
        if any(keyword in context for keyword in keywords):
            selected.add(skill_name)
    return sorted(selected)


def load_role_surface(role_root: Path, selected_skills: list[str] | None = None) -> str:
    parts: list[str] = []
    agents_path = role_root / "AGENTS.md"
    if agents_path.exists():
        parts.append(f"Role AGENTS ({agents_path}):\n{agents_path.read_text(encoding='utf-8')}")
    skills_root = role_root / "skills"
    if skills_root.exists():
        allowed = {item.strip().lower() for item in selected_skills or [] if item and item.strip()}
        for skill_path in sorted(skills_root.glob("*/SKILL.md")):
            if allowed and skill_path.parent.name.lower() not in allowed:
                continue
            parts.append(f"Role skill ({skill_path}):\n{skill_path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts).strip()


def build_runtime_whitelist(paths) -> list[str]:
    return [
        str(paths.person_program),
        str(paths.agent_program),
        str(paths.task_state),
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
    task_state: dict[str, Any],
    poll_seconds: int,
    report_path: str,
    supervisor_template: str,
    execution_backend: str | None = None,
    legacy_task: str | None = None,
) -> str:
    role = role.strip().lower()
    if role not in ROLE_VALUES:
        raise ValueError(f"Unknown role: {role}")
    if paths is None:
        from scripts.research_loop_contract import resolve_artifact_paths
        paths = resolve_artifact_paths(ROOT_DIR, load_project_config(ROOT_DIR))
    explicit_backend = execution_backend or task_state.get("execution_backend")
    effective_backend = str(explicit_backend or "ssh")
    legacy_block = f"\nLegacy request context:\n{legacy_task}\n" if legacy_task else ""
    role_root = paths.reader_role_root if role == "reader" else paths.runner_role_root
    selected_skills = select_role_skills(role, task_state, agent_program_full, str(explicit_backend) if explicit_backend else None)
    role_surface_block = load_role_surface(role_root, selected_skills)
    extra_role_rules = ""
    if role == "reader":
        whitelist = "\n".join(f"  - {item}" for item in build_runtime_whitelist(paths))
        extra_role_rules = (
            "\nReader read whitelist:\n"
            f"{whitelist}\n"
            "- Stay inside this whitelist first; only broaden reads when the current step cannot be completed from these files.\n"
            "- At the end of the reader turn, hardcode `task-state.json` to hand off to `runner` by setting:\n"
            "  - `phase = \"runner\"`\n"
            "  - `next_action = \"runner\"`\n"
        )
    else:
        if effective_backend == "local":
            extra_role_rules = (
                "\nRunner-owned state transition:\n"
                "- You are in LOCAL execution mode.\n"
                "- Do not require SSH, SCP, `remote_code_dir`, or `remote_result_dir`.\n"
                "- Launch long experiments as local background processes through the local supervisor command in the template below.\n"
                "- Write compact evidence to `local.result_dir` and keep `local_evidence_paths` local-only.\n"
                "- After launch, set `task-state.json` to `phase = \"watch\"`, `next_action = \"watch\"`, `execution_backend = \"local\"`, and `execution_status = \"running\"`.\n"
                "- If the experiment is judged successful, or `runner_iteration` has reached `runner_iteration_cap`, set `task-state.json` back to `reader`.\n"
                "- Otherwise, set the next state needed for execution continuation, typically `watch` after a local launch.\n"
            )
        else:
            extra_role_rules = (
                "\nRunner-owned state transition:\n"
                "- You are in SSH execution mode.\n"
                "- You may implement or modify local code first when the assignment requires missing code, boundary fixes, or local scaffold work.\n"
                "- Smoke and formal experiments run through the configured SSH backend.\n"
                "- Before finishing a remote run, prune `remote_result_dir`: delete bulky intermediate or process files that do not need to be synced back.\n"
                "- Leave only the compact core result set needed locally (for example decision, metrics, summary, manifest, and other explicitly needed artifacts).\n"
                "- If a large artifact might matter later, summarize it in a small retained file instead of leaving the full bulky file in `remote_result_dir` by default.\n"
                "- You own the post-run state change.\n"
                "- If the experiment is judged successful, or `runner_iteration` has reached `runner_iteration_cap`, set `task-state.json` back to `reader`.\n"
                "- Otherwise, set the next state needed for execution continuation, typically `watch` after a remote launch.\n"
            )
    observatory_rules = (
        "\nObservatory dashboard data maintenance (required before finishing this turn):\n"
        "- Directly maintain the static dashboard data files when your turn changes the research state:\n"
        "  - `files/data/plan.json` for Plan & Progress cards.\n"
        "  - `files/data/agents.json` for reader/runner/system activity events.\n"
        "  - `files/data/glossary.json` for concepts, methods, benchmarks, artifacts, and sources.\n"
        "- Reader and runner may update all three Observatory JSON files; keep prior useful history and append activity events instead of replacing the log.\n"
        "- Keep the files valid UTF-8 JSON matching the existing `files/index.html` contract. If a file is missing, create a minimal valid default (`[]` for plan/agents, `{}` for glossary).\n"
        "- Do not stream or expose full internal chain-of-thought. Write concise public summaries, evidence, outputs, blockers, decisions, and next actions only.\n"
        "- The dashboard's Outbound Prompts panel is backed by `/api/prompt`; do not replace it with browser-only/localStorage delivery logic.\n"
    )
    extra_role_rules += observatory_rules

    applied_prompt = task_state.get("applied_human_prompt") or task_state.get("pending_human_prompt")
    prompt_block = ""
    if isinstance(applied_prompt, dict) and applied_prompt.get("text"):
        prompt_block = (
            "\nONE-TIME HUMAN PROMPT FOR THIS INVOCATION:\n"
            f"- Target: {applied_prompt.get('target')}\n"
            f"- Instruction: {applied_prompt.get('text')}\n"
            "- This instruction is one-shot and applies only to the current invocation.\n"
        )
    runner_execution_requirement = (
        "- Runner may implement or modify local code, but experiment launch/watch must follow the configured execution backend."
        if role == "runner"
        else "- Runner may implement or modify local code within the assignment bounds."
    )
    return f"""Execute the current sub-PHD loop step for role={role}.

ROLE NOTE:
{DEFAULT_ROLE_NOTES[role]}

PERSON PROGRAM (human-owned):
{person_program_full}

AGENT PROGRAM (reader-writable):
{agent_program_full}

CURRENT TASK STATE:
{json.dumps(task_state, ensure_ascii=False, indent=2)}
{legacy_block}
Execution requirements:
- Use the role contract above; do not violate artifact ownership.
- Reader owns semantic handoff authoring and may edit `agent_program.md`.
{runner_execution_requirement}
- Reader and runner are context-isolated; continue work from artifacts, not from shared conversational memory.
- Program sources are intentionally compact in this prompt; use the file paths + hashes below and read the files from disk when needed.
- Use the backend-appropriate supervisor watch command for long-running monitoring rather than rediscovering active runs repeatedly.
- Poll cadence reference: every {poll_seconds} seconds.
- Write final role summary to: `{report_path}`.
{extra_role_rules}
{prompt_block}

Project-local role surface:
{role_surface_block or '(No additional role surface files found)'}

Activated role-local skills for this turn:
- {", ".join(selected_skills)}

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


def run_codex_command(cmd: list[str], *, cwd: Path, prompt_text: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        input=prompt_text,
        text=True,
        encoding="utf-8",
    )


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
    execution_backend: str = "ssh",
) -> Path:
    from scripts.research_loop_contract import atomic_write_json
    if metadata_path.suffix.lower() != ".json":
        metadata_path = metadata_path / ".omx" / "last-launch-metadata.json"
    if execution_backend == "local":
        canonical_transport_marker = "scripts/research_supervisor.py launch --backend local"
        canonical_watch_marker = "scripts/research_supervisor.py watch-backend --backend local"
    else:
        canonical_transport_marker = "scripts/research_supervisor.py launch-bash"
        canonical_watch_marker = "scripts/research_supervisor.py watch"
    payload = {
        "role": role,
        "execution_backend": execution_backend,
        "rendered_prompt_hash": rendered_prompt_hash,
        "role_surface_root": str(role_surface_root) if role_surface_root else None,
        "prompt_file": str(prompt_file),
        "command_file": str(command_file),
        "report_file": str(report_file),
        "canonical_transport_marker": canonical_transport_marker,
        "canonical_watch_marker": canonical_watch_marker,
        "updated_at": now_utc_iso(),
    }
    atomic_write_json(metadata_path, payload)
    return metadata_path


def normalize_post_role_run_state(role: str, task_state: dict[str, Any]) -> dict[str, Any]:
    """Normalize state after a role run completes.

    Reader always transitions to runner.
    Runner: respect runner's own phase/next_action choice for watch, terminal,
    or continuation within cap. Only force to reader when cap is exhausted or
    runner didn't make a choice.
    """
    normalized = dict(task_state)
    if role == "reader":
        normalized["phase"] = "runner"
        normalized["next_action"] = "runner"
        return normalized

    # Runner post-processing: respect runner's own choice
    runner_phase = normalized.get("phase")
    runner_next = normalized.get("next_action")

    # Runner must NOT declare sprint done/abandoned — autoloop decides.
    # Only "needs_human" passes through directly.
    if runner_phase == "needs_human":
        return normalized
    if runner_phase in {"done", "abandoned"}:
        normalized["phase"] = "reader"
        normalized["next_action"] = "reader"
        return normalized

    # Runner explicitly wants watch — respect it
    if runner_phase == "watch" or runner_next == "watch":
        return normalized

    # Runner wants to stay runner and cap not exhausted — respect it
    if runner_phase == "runner" or runner_next == "runner":
        if int(normalized.get("runner_iteration", 0)) < int(normalized.get("runner_iteration_cap", 1)):
            return normalized

    # Default: transition to reader (cap exhausted or no explicit choice)
    normalized["phase"] = "reader"
    normalized["next_action"] = "reader"
    return normalized


def validate_sprint_contract(sc: dict[str, Any] | None) -> tuple[bool, list[str]]:
    """Validate a sprint_contract, returning (ok, warnings).

    Rules:
    - sprint_type is required
    - success_condition must include at least one metric condition
    - Pure artifact conditions only allowed for sprint_type="terminal_collection"
    - Legacy string success_condition is accepted with a warning

    Returns (True, []) if the contract looks valid.
    Returns (False, [warnings]) if issues found (non-blocking).
    """
    if not isinstance(sc, dict) or not sc:
        return False, ["sprint_contract is missing or empty"]

    warnings: list[str] = []
    sc_type = sc.get("sprint_type")

    if not sc_type:
        return False, warnings + ["sprint_contract.sprint_type is missing — should be one of: diagnostic, construction, sweep, terminal_collection"]
    if sc_type not in ("diagnostic", "construction", "sweep", "terminal_collection"):
        warnings.append(
            f"sprint_contract.sprint_type={sc_type!r} is not recognized — should be one of: diagnostic, construction, sweep, terminal_collection"
        )

    success = sc.get("success_condition")
    if not success:
        return False, warnings + ["sprint_contract.success_condition is missing"]

    # Legacy string success_condition
    if isinstance(success, str):
        return True, warnings + [
            "sprint_contract.success_condition is a legacy string — consider upgrading to structured format with at least one metric condition"
        ]

    if not isinstance(success, dict):
        return False, warnings + [f"sprint_contract.success_condition has unexpected type: {type(success).__name__}"]

    conditions = success.get("conditions") or []
    if not isinstance(conditions, list):
        return False, warnings + ["sprint_contract.success_condition.conditions is not a list"]

    has_metric = any(
        isinstance(c, dict) and c.get("metric")
        for c in conditions
    )
    has_artifact = any(
        isinstance(c, dict) and "artifact" in c
        for c in conditions
    )

    if not has_metric:
        if sc_type == "terminal_collection":
            if has_artifact:
                return True, warnings  # terminal with artifact-only is OK
            return False, warnings + [
                "sprint_contract.success_condition has no metric or artifact conditions"
            ]
        else:
            return False, warnings + [
                f"sprint_contract.success_condition must include at least one metric condition when sprint_type={sc_type!r}. Pure artifact conditions are only allowed for sprint_type='terminal_collection'."
            ]

    return True, warnings



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
    task_state = load_task_state(paths.task_state)
    role = args.role or task_state["phase"]
    role_surface_root = paths.reader_role_root if role == "reader" else paths.runner_role_root
    poll_seconds = int(args.poll_seconds) if args.poll_seconds is not None else int(config.get("default_poll_seconds", 300))
    model = args.model or config.get("default_model", "gpt-5.4")
    person_program_text = read_validated_text(paths.person_program, "person_program")
    agent_program_text = read_validated_text(paths.agent_program, "agent_program")
    execution_backend = resolve_execution_backend(config)
    if role == "runner":
        ensure_runner_backend_requirements(config)
        if args.task:
            raise ValueError("runner mode rejects ad-hoc local task injection; use reader-produced artifacts only")

    # Validate sprint_contract if present
    sc = task_state.get("sprint_contract")
    if sc:
        ok, sc_warnings = validate_sprint_contract(sc)
        if not ok:
            append_ai_worklog_entry(
                paths.ai_worklog,
                {
                    "role": role,
                    "start_time": now_utc_iso(),
                    "current_objective": task_state.get("current_objective", ""),
                    "success_condition": f"VALIDATION WARNING: {'; '.join(sc_warnings)}",
                    "next_action": task_state.get("next_action", ""),
                },
            )
            print(f"[{role}] sprint_contract validation: {'; '.join(sc_warnings)}")
        elif sc_warnings:
            print(f"[{role}] sprint_contract advisory: {'; '.join(sc_warnings)}")

    prompt_hash = compute_prompt_contract_hash(
        person_program_text, agent_program_text, role, task_state
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

    prompt_text = build_role_prompt(
        role=role,
        paths=paths,
        person_program=person_program_summary,
        agent_program=agent_program_summary,
        person_program_full=person_program_text,
        agent_program_full=agent_program_text,
        task_state=task_state,
        poll_seconds=poll_seconds,
        report_path=str(report_file),
        supervisor_template=supervisor_template,
        execution_backend=execution_backend,
        legacy_task=args.task,
    )
    prompt_file = write_prompt_file(paths.prompts_root, prompt_text)
    output_file = paths.last_agent_message
    output_file.parent.mkdir(parents=True, exist_ok=True)

    task_state["prompt_contract_hash"] = prompt_hash
    task_state["agent_program_ref"] = text_sha256(agent_program_text)
    task_state["updated_at"] = now_utc_iso()
    from scripts.research_loop_contract import atomic_write_json
    atomic_write_json(paths.task_state, task_state)

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
        execution_backend=execution_backend,
    )

    pending = task_state.get("pending_human_prompt")
    if isinstance(pending, dict) and pending.get("text") and not args.dry_run:
        task_state = consume_pending_human_prompt_if_matched(
            task_state,
            matched_prompt=pending,
        )
        task_state["last_applied_human_prompt"]["applied_role"] = role
        task_state["updated_at"] = now_utc_iso()
        atomic_write_json(paths.task_state, task_state)

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
    completed = run_codex_command(cmd, cwd=role_surface_root, prompt_text=prompt_text)
    try:
        latest_task_state = load_task_state(paths.task_state)
    except Exception:
        latest_task_state = task_state
    latest_task_state = normalize_post_role_run_state(role, latest_task_state)
    atomic_write_json(paths.task_state, latest_task_state)
    append_ai_worklog_entry(
        paths.ai_worklog,
        {
            "role": role,
            "start_time": start_time,
            "current_objective": latest_task_state.get("current_objective", ""),
            "runner_iteration": latest_task_state.get("runner_iteration", 0),
            "runner_iteration_cap": latest_task_state.get("runner_iteration_cap", 0),
            "reader_iteration": latest_task_state.get("reader_iteration", 0),
            "reader_iteration_cap": latest_task_state.get("reader_iteration_cap", 0),
            "success_condition": latest_task_state.get("success_condition", ""),
            "remote_status": latest_task_state.get("remote_status", ""),
            "latest_result_summary": latest_task_state.get("last_result_summary", ""),
            "next_action": latest_task_state.get("next_action", ""),
        },
    )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
