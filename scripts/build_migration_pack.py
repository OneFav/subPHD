#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.research_agent_cli import load_project_config
from scripts.research_loop_contract import (
    atomic_write_json,
    atomic_write_text,
    default_task_state,
    default_watch_snapshot,
    now_utc_iso,
    resolve_artifact_paths,
)

PACK_NAME = "subphd-migration-pack"
SCRIPT_FILES = [
    "recover_autoresearch_state.py",
    "research_agent_cli.py",
    "research_autoloop.py",
    "research_dashboard.py",
    "research_loop_contract.py",
    "research_reporting.py",
    "research_supervisor.py",
]
ROOT_FILES_TO_COPY = [
    "start.bat",
    "resume.bat",
]


def render_start_bat() -> str:
    return """@echo off
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

  set "MAX_RUNS=100"
  set "HOURS=1"

if not "%~1"=="" set "MAX_RUNS=%~1"
if not "%~2"=="" set "HOURS=%~2"

set "PYTHON_CMD=python"
where python >nul 2>nul
if errorlevel 1 (
  set "PYTHON_CMD=py -3"
)

echo [sub-PHD] Root: %ROOT%
echo [sub-PHD] Resetting runtime state...
%PYTHON_CMD% -c "from pathlib import Path; from scripts.research_agent_cli import load_project_config; from scripts.research_loop_contract import bootstrap_state_artifacts, reset_runtime_state; root = Path(r'%ROOT%'); config = load_project_config(root); paths = bootstrap_state_artifacts(root, config); reset_runtime_state(paths, config, reason='start_bat_fresh_start'); print('[sub-PHD] Runtime reset complete:', paths.runtime_root)"
if errorlevel 1 (
  set "AUTOLOOP_RC=%ERRORLEVEL%"
  echo.
  echo [sub-PHD] Runtime reset failed with code %AUTOLOOP_RC%.
  pause >nul
  endlocal & exit /b %AUTOLOOP_RC%
)

echo [sub-PHD] Starting dashboard...
start "sub-PHD Dashboard" cmd /k %PYTHON_CMD% scripts\\research_dashboard.py --workdir "%ROOT%" --port 0

echo [sub-PHD] Starting autoloop with --max-runs %MAX_RUNS% --hours %HOURS% --ignore-state
%PYTHON_CMD% scripts\\research_autoloop.py --workdir "%ROOT%" --max-runs %MAX_RUNS% --hours %HOURS% --ignore-state
set "AUTOLOOP_RC=%ERRORLEVEL%"

if not "%AUTOLOOP_RC%"=="0" (
  echo.
  echo [sub-PHD] Autoloop exited with code %AUTOLOOP_RC%.
  echo [sub-PHD] The window will stay open so you can read the error.
  pause >nul
)

endlocal & exit /b %AUTOLOOP_RC%
"""


def render_resume_bat() -> str:
    return """@echo off
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

  set "MAX_RUNS=100"
  set "HOURS=1"

if not "%~1"=="" set "MAX_RUNS=%~1"
if not "%~2"=="" set "HOURS=%~2"

set "PYTHON_CMD=python"
where python >nul 2>nul
if errorlevel 1 (
  set "PYTHON_CMD=py -3"
)

echo [sub-PHD] Root: %ROOT%
echo [sub-PHD] Resuming existing runtime state...

echo [sub-PHD] Starting dashboard...
start "sub-PHD Dashboard" cmd /k %PYTHON_CMD% scripts\\research_dashboard.py --workdir "%ROOT%" --port 0

echo [sub-PHD] Resuming autoloop with --max-runs %MAX_RUNS% --hours %HOURS%
%PYTHON_CMD% scripts\\research_autoloop.py --workdir "%ROOT%" --max-runs %MAX_RUNS% --hours %HOURS%
set "AUTOLOOP_RC=%ERRORLEVEL%"

if not "%AUTOLOOP_RC%"=="0" (
  echo.
  echo [sub-PHD] Autoloop exited with code %AUTOLOOP_RC%.
  echo [sub-PHD] The window will stay open so you can read the error.
  pause >nul
)

endlocal & exit /b %AUTOLOOP_RC%
"""


def render_template_person_program() -> str:
    return """# person_program.md

## Current Mission
Describe the new project goal in plain language. Be concrete about what the loop is trying to learn, build, or validate.

## Priority Order
1. Highest-priority outcome for this project
2. Evidence or artifact that must exist next
3. Secondary improvement or stretch goal

## Reader Responsibilities
- define the next bounded objective
- decide what evidence is required before handoff
- keep the assignment narrow, explicit, and testable

## Runner Responsibilities
- stay inside the current assignment bounds
- modify local code only when needed
- keep smoke/formal experiments remote-only unless you intentionally change that contract

## Success Condition
State what counts as success for this loop, what evidence must exist, and what would mean the loop should stop or hand back to the reader.

## Notes
Use this file as the only required human-authored control document for a new project. You can keep the first version simple, then refine it over time as the reader clarifies the lane.
"""


def render_research_agent_toml(config: dict) -> str:
    project_name = str(config.get("project_name") or PACK_NAME)
    default_model = str(config.get("default_model") or "gpt-5.4")
    default_hours = int(config.get("default_hours") or 10)
    default_max_runs = int(config.get("default_max_runs") or 30)
    default_poll_seconds = int(config.get("default_poll_seconds") or 300)
    remote = config.get("remote", {}) if isinstance(config, dict) else {}
    logs = config.get("logs", {}) if isinstance(config, dict) else {}
    artifacts = config.get("artifacts", {}) if isinstance(config, dict) else {}
    loop = config.get("loop", {}) if isinstance(config, dict) else {}
    runtime = config.get("runtime", {}) if isinstance(config, dict) else {}

    def normalize_artifact(name: str, default: str) -> str:
        raw = str(artifacts.get(name, default))
        return default if raw.startswith(".omx/") else raw

    return f"""project_name = "{project_name}"
default_model = "{default_model}"
default_hours = {default_hours}
default_max_runs = {default_max_runs}
default_poll_seconds = {default_poll_seconds}

[remote]
ssh_key = "{remote.get('ssh_key', '')}"
host = "{remote.get('host', '')}"
port = {int(remote.get('port', 22) or 22)}
remote_code_dir = "{remote.get('remote_code_dir', '')}"
remote_result_dir = "{remote.get('remote_result_dir', '')}"
gpu_count = {int(remote.get('gpu_count', loop.get('gpu_count', 1)) or 1)}

[logs]
results_jsonl = "{logs.get('results_jsonl', 'research/results.jsonl')}"
experiment_log_md = "{logs.get('experiment_log_md', 'research/EXPERIMENT_LOG.md')}"
claims_md = "{logs.get('claims_md', 'research/CLAIMS.md')}"
memory_md = "{logs.get('memory_md', 'research/MEMORY.md')}"
next_experiment_md = "{logs.get('next_experiment_md', 'research/NEXT_EXPERIMENT.md')}"

[artifacts]
person_program = "{normalize_artifact('person_program', 'person_program.md')}"
agent_program = "{normalize_artifact('agent_program', 'agent_program.md')}"
loop_state = "{normalize_artifact('loop_state', '.subphd/state/research_loop_state.json')}"
watch_snapshot = "{normalize_artifact('watch_snapshot', '.subphd/state/research_watch_snapshot.json')}"
watch_events = "{normalize_artifact('watch_events', '.subphd/state/research_watch_events.jsonl')}"
run_state = "{normalize_artifact('run_state', '.subphd/state/run-state.json')}"
ai_worklog = "{normalize_artifact('ai_worklog', '.subphd/logs/ai-worklog.md')}"


[runtime]
root = "{runtime.get('root', '.subphd') if str(runtime.get('root', '.subphd')) != '.omx' else '.subphd'}"
workspace_root = "{runtime.get('workspace_root', '.')}"
roles_root = "{runtime.get('roles_root', 'roles')}"
backend = "{runtime.get('backend', 'codex')}"
compat_omx_export = {str(bool(runtime.get('compat_omx_export', False))).lower()}
legacy_runtime_root = "{runtime.get('legacy_runtime_root', '.autoresearch')}"

[loop]
slow_heartbeat_seconds = {int(loop.get('slow_heartbeat_seconds', default_poll_seconds) or default_poll_seconds)}
gpu_count = {int(loop.get('gpu_count', remote.get('gpu_count', 1)) or 1)}
"""


def render_migration_readme() -> str:
    return """# sub-PHD Migration Pack

This template is a reusable starter pack for the local sub-PHD runtime.

## What is already initialized
- `person_program.md` is a valid starter template
- `agent_program.md` is initialized
- `.subphd/state/*.json` starts from a fresh `reader` state
- `sub-PHD` observability starts empty
- SSH connection parameters are preserved in `research_agent.toml`
- project-local `roles/reader` and `roles/runner` surfaces are present
  - no separate workspace directory is required; agents work directly in the repo tree

## What you usually need to change in a new project
1. Edit `person_program.md`
2. If the new project uses a different remote checkout path, update:
   - `remote_code_dir`
   - `remote_result_dir`
3. If needed, adjust project-specific files under `research/`

## Fresh start commands
```bash
python scripts/research_autoloop.py --workdir . --ignore-state
python scripts/research_dashboard.py --workdir .
```

## Notes
- `--ignore-state` resets the loop to a fresh task start (`reader`) and clears the dashboard timeline.
- `agent_program.md` can remain auto-managed; the human only needs to maintain `person_program.md` to get started.
- Continuity uses role-local windows with a short resume budget rather than unbounded same-chat history.
- The authoritative handoff under the reports root should be treated as the first continuity source before generic recent reports.
"""


def render_pack_readme() -> str:
    return """# sub-PHD Migration Starter

This package contains the minimal reusable sub-PHD runtime framework for moving into a new project.

## Included
- `person_program.md`
- `agent_program.md`
- `research_agent.toml` (SSH/remote connection preserved)
- `start.bat` (fresh start)
- `resume.bat` (resume current state)
- `.subphd/` fresh runtime state
- `roles/reader/`
- `roles/runner/`
- `scripts/`
- lightweight `research/` placeholders for log files referenced by config

## Not included
- project-specific research code
- old runtime state/history from the source project
- old reports/prompts/commands/synced results
- benchmark-specific artifacts

## Typical migration steps
1. Copy or unzip this starter into the new repo.
2. Replace `person_program.md` with the new mission.
3. Keep or update the remote SSH settings in `research_agent.toml`.
4. Add new project-specific code under `research/` if needed.
5. Start with:
   - `start.bat` for a new task
   - `resume.bat` to continue existing state

## Notes
- `start.bat` resets `.subphd/state/*` before launching.
- `resume.bat` reuses current `.subphd/state/*`.
- The canonical runtime root is `.subphd/`.
- Continuity uses role-local windows with a short resume budget.
- The authoritative handoff under the reports root is the first continuity source before generic recent reports.
"""


def render_pack_readme_zh() -> str:
    return """# sub-PHD 迁移启动包

这个包是可迁移到新项目的最小 sub-PHD 运行时框架。

## 已包含
- `person_program.md`
- `agent_program.md`
- `research_agent.toml`（保留开发机 SSH / 远程连接参数）
- `start.bat`（新任务启动）
- `resume.bat`（续跑当前状态）
- `.subphd/` 新初始化状态
- `roles/reader/`
- `roles/runner/`
- `scripts/`
- `research/` 下极简占位日志文件

## 不包含
- 当前项目的研究代码
- 当前项目旧的运行状态和历史
- 旧 reports / prompts / commands / synced results
- benchmark 专属产物

## 迁移到新项目时通常怎么做
1. 把这个启动包复制或解压到新项目里。
2. 改写 `person_program.md`。
3. 按需保留或修改 `research_agent.toml` 里的远程 SSH 参数。
4. 如果需要，在 `research/` 下加入新项目自己的代码。
5. 启动时：
   - 新任务用 `start.bat`
   - 续跑用 `resume.bat`

## 说明
- `start.bat` 会先重置 `.subphd/state/*`。
- `resume.bat` 会复用当前 `.subphd/state/*`。
- 当前 canonical runtime 根目录是 `.subphd/`。
"""


def ensure_empty_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")


def build_migration_pack(root: Path, output_dir: Path) -> tuple[Path, Path]:
    config = load_project_config(root)
    pack_root = output_dir / PACK_NAME
    if pack_root.exists():
        shutil.rmtree(pack_root)
    pack_root.mkdir(parents=True, exist_ok=True)

    scripts_dir = pack_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for name in SCRIPT_FILES:
        shutil.copy2(root / "scripts" / name, scripts_dir / name)
    for name in ROOT_FILES_TO_COPY:
        source = root / name
        if source.exists():
            shutil.copy2(source, pack_root / name)
    if not (pack_root / "start.bat").exists():
        atomic_write_text(pack_root / "start.bat", render_start_bat())
    if not (pack_root / "resume.bat").exists():
        atomic_write_text(pack_root / "resume.bat", render_resume_bat())

    atomic_write_text(pack_root / "research_agent.toml", render_research_agent_toml(config))
    atomic_write_text(pack_root / "person_program.md", render_template_person_program())
    atomic_write_text(pack_root / "agent_program.md", "# agent_program.md\n\n## Current Strategy\n- Reader may edit this file directly.\n- Default posture: prioritize explicit, traceable, budget-aware research progress.\n\n## Revision Suggestions\n- None yet.\n")
    atomic_write_text(pack_root / "README.md", render_pack_readme())
    atomic_write_text(pack_root / "README.zh-CN.md", render_pack_readme_zh())
    atomic_write_text(pack_root / "README-migrate.md", render_migration_readme())

    pack_config = load_project_config(pack_root)
    paths = resolve_artifact_paths(pack_root, pack_config)

    # Initialized runtime state
    for directory in [
        paths.runtime_root,
        paths.state_root,
        paths.logs_root,
        paths.reports_root,
        paths.prompts_root,
        paths.commands_root,
        paths.synced_results_root,
        paths.autoloop_root,
        paths.roles_root,
    ]:
        directory.mkdir(parents=True, exist_ok=True)
    # Copy role surface files from source project if they exist
    source_reader = paths.workspace_root / "roles" / "reader" / "AGENTS.md"
    source_runner = paths.workspace_root / "roles" / "runner" / "AGENTS.md"
    for role_name, role_root, source in [
        ("reader", paths.reader_role_root, source_reader),
        ("runner", paths.runner_role_root, source_runner),
    ]:
        role_root.mkdir(parents=True, exist_ok=True)
        agent_path = role_root / "AGENTS.md"
        if not agent_path.exists() and source.exists():
            agent_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    atomic_write_json(paths.task_state, default_task_state(pack_config))
    atomic_write_json(paths.watch_snapshot, default_watch_snapshot())
    ensure_empty_file(paths.watch_events)
    ensure_empty_file(paths.ai_worklog)

    # Placeholder research outputs referenced by the config
    logs_cfg = config.get("logs", {}) if isinstance(config, dict) else {}
    for relative, content in [
        (logs_cfg.get("results_jsonl", "research/results.jsonl"), ""),
        (logs_cfg.get("experiment_log_md", "research/EXPERIMENT_LOG.md"), "# Experiment Log\n"),
        (logs_cfg.get("claims_md", "research/CLAIMS.md"), "# Claims\n"),
        (logs_cfg.get("memory_md", "research/MEMORY.md"), "# Memory\n"),
        (logs_cfg.get("next_experiment_md", "research/NEXT_EXPERIMENT.md"), "# Next Experiment\n"),
    ]:
        target = pack_root / str(relative)
        atomic_write_text(target, content)

    archive_base = output_dir / PACK_NAME
    zip_path = Path(shutil.make_archive(str(archive_base), "zip", root_dir=output_dir, base_dir=PACK_NAME))
    return pack_root, zip_path


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Build a reusable sub-PHD migration pack with fresh state and preserved SSH config.")
    ap.add_argument("--workdir", default=".")
    ap.add_argument("--output-dir", default="dist")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.workdir).resolve()
    output_dir = (root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pack_root, zip_path = build_migration_pack(root, output_dir)
    print(f"Migration pack directory: {pack_root}")
    print(f"Migration pack zip: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
