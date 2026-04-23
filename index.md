# Agent Initialization Index

This file is the first entrypoint for an agent that is helping a user initialize this starter.

## Purpose
- Turn this repository into a project-specific working starter without requiring the user to edit internal framework files.
- Keep the user-owned surface small:
  - `person_program.md`
  - project code placed under `research/`

## Ownership Rules
- The agent may edit framework-owned files such as:
  - `research_agent.toml`
  - `agent_program.md`
  - docs and helper files under the starter itself
- The agent must not automatically modify the user's existing business code under `research/`.

## Initialization Flow
1. Read this file before any other onboarding action.
2. Make the two repo-shipped sub-PHD skills available to Codex before continuing:
   - `skills/subphd-run-disclosure/`
   - `skills/subphd-program-refinement/`
   Deploy them into the active Codex skills environment by copying, linking, or otherwise installing them in the user's Codex skill path.
3. Inspect the current repository state.
4. Ask the user the minimum setup questions needed to initialize the starter.
5. Fill framework-owned configuration files.
6. Run the validation steps below.
7. Report the final startup commands back to the user.

## Required sub-PHD skills
This starter now ships two companion skills that should be available to Codex during normal use:

- `subphd-run-disclosure`
  - Use this to understand what the current sub-PHD run window is doing, what evidence exists, and how complete the run is versus `person_program.md`.
- `subphd-program-refinement`
  - Use this to refine or rewrite `person_program.md` when the current mission becomes stale, too narrow, or misaligned with the newest evidence.

If those skills are not yet available in the active Codex environment, deploy them before setup finishes.

## Questions To Ask The User
- What is the project trying to do?
  - Use the answer to shape `person_program.md`.
- What code should live under `research/`?
  - Move or confirm user code there, but do not silently rewrite business logic.
- Should this project use SSH / remote execution?
  - If yes, ask for:
    - `ssh_key`
    - `host`
    - `port`
    - `remote_code_dir`
    - `remote_result_dir`
- What runtime defaults should be used if the user wants to override them?
  - `default_max_runs`
  - `default_hours`
  - `default_poll_seconds`

## Configuration Rules
- This repository ships with empty SSH defaults.
- If the user wants SSH, populate the `remote` section in `research_agent.toml`.
- If the user does not want SSH yet, leave the `remote` values empty and keep the local starter usable.
- Keep `person_program.md` human-owned.
- Treat `agent_program.md` as framework-managed unless the user explicitly asks otherwise.

## Required Validation
Run these checks after initialization changes.

### Local toolchain checks
```powershell
python --version
codex --version
```

### Starter smoke checks
```powershell
python scripts\research_agent_cli.py --workdir . --role reader --dry-run
python scripts\research_agent_cli.py --workdir . --role runner --dry-run
python scripts\research_autoloop.py --workdir . --max-runs 1 --hours 0.01 --ignore-state --dry-run
```

### SSH validation
- Only run this after the user has confirmed remote execution should be enabled.
- Stop and ask for confirmation before the first remote connection or remote execution.
- Suggested validation command:

```powershell
ssh -i <ssh_key> -p <port> -o BatchMode=yes -o StrictHostKeyChecking=accept-new <host> "echo connected && hostname && pwd"
```

## What To Tell The User At The End
Always report both command-line and batch-file startup options.

### Command-line
```powershell
python scripts\research_autoloop.py --workdir . --ignore-state
python scripts\research_dashboard.py --workdir .
```

### Batch files
```powershell
start.bat
resume.bat
```

## Steady-State User Workflow
After initialization, the intended user workflow is:
1. put project code under `research/`
2. use `subphd-program-refinement` when you want Codex to improve or rewrite `person_program.md`
3. use `subphd-run-disclosure` when you want Codex to explain what the current run is doing and what evidence it has produced
4. start the loop with the command-line or `.bat` entrypoint

## Non-Goals
- Do not automatically rewrite user business code.
- Do not silently perform remote execution before confirmation.
- Do not require the user to manually patch framework internals during ordinary setup.
