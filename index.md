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


## Optional external carrier-agent skills
This starter may also include three optional external carrier-agent examples for assistants such as Hermes, OpenClaw, Claude Code, Codex, or custom agents that manage multiple sub-PHD projects from outside the runtime:

- `skills/subphd-inspect/`
- `skills/subphd-control/`
- `skills/subphd-watch/`

What changed:
- `subphd-inspect` gives an external assistant a read-only way to answer status, evidence, progress, and cross-project summary questions across one or more sub-PHD projects.
- `subphd-control` gives an external assistant guarded lifecycle instructions for start/resume, exact-process stop guidance, and new-project creation/registration through official sub-PHD entrypoints and explicit confirmation gates.
- `subphd-watch` gives an external assistant a carrier-side watch-rule contract for reminders, alerts, periodic summaries, list/update/cancel operations, and cooldown/conflict handling.

These are **not** part of the mandatory two-skill initialization flow above. Do not add them to Step 2 unless the user explicitly wants external carrier-agent control. They are also separate from Reader/Runner role-local skills under `roles/`.

Protocol summary:
- Project resolution goes through `~/.subphd-agent/projects.json` or `%USERPROFILE%\.subphd-agent\projects.json`, or a carrier-agent override. Do not scan disks.
- Watch rules live in `~/.subphd-agent/watch-rules.json` or `%USERPROFILE%\.subphd-agent\watch-rules.json`, or a carrier-agent override. Do not write watch rules into project directories.
- Start/resume control still goes through `start.bat`, `resume.bat`, or `python scripts/research_autoloop.py`; there is no official `stop.bat` in this pass.
- Migration packs copy these optional external skills and `docs/subphd-agent-protocol.md` so the `index.md` protocol link remains valid after packaging.
- Full protocol in the source repository: `docs/subphd-agent-protocol.md`.

## Questions To Ask The User
- What is the project trying to do?
  - Use the answer to shape `person_program.md`.
- What code should live under `research/`?
  - Move or confirm user code there, but do not silently rewrite business logic.
- Should this project run experiments locally or through SSH?
  - Local means the current machine is the experiment machine, even if the current machine is already a remote development server.
  - SSH means this starter controls a separate experiment machine through SSH/SCP.
  - If SSH, ask for:
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
- Execution backend is selected in `research_agent.toml`:
  - `execution.backend = "local"` for local background experiments.
  - `execution.backend = "ssh"` for SSH-controlled remote experiments.
- If the user wants SSH, set `execution.backend = "ssh"` and populate the `remote` section in `research_agent.toml`.
- If the user does not want SSH, set `execution.backend = "local"` and leave the `remote` values empty.
- Keep `person_program.md` human-owned.
- Treat `agent_program.md` as framework-managed unless the user explicitly asks otherwise.

## Execution Backend Implementation Notes For Agents

The autoresearch loop is intentionally backend-neutral:

```text
reader -> runner -> watch -> reader/runner
```

The backend only changes how runner launches experiments and how watch observes them.

### Implementation surface
When changing backend behavior, update these files together so the agent prompt, loop state, and supervisor stay consistent:

- `research_agent.toml`: user-facing backend switch and backend-specific defaults.
- `scripts/research_loop_contract.py`: backend enum, config resolution, default loop/run/watch state, state validation, and local runner skill templates.
- `scripts/research_agent_cli.py`: runner backend validation, selected runner skills, generated prompt text, and launch metadata.
- `scripts/research_supervisor.py`: actual launch/watch implementation. SSH uses `launch-bash` and `watch`; local uses `launch --backend local` and `watch-backend --backend local`.
- `scripts/research_autoloop.py`: chooses `watch_local` or `watch_remote` from `run-state.json.execution_backend` or `research_agent.toml.execution.backend`, then applies `advance_run_state_after_watch`.
- `roles/runner/AGENTS.md` and `roles/runner/skills/`: backend-neutral runner contract plus optional backend-specific skills such as `local-experiment` and `local-watch`.

### Local backend
Use local mode when the current machine should run the experiment:

```toml
[execution]
backend = "local"

[local]
workdir = "."
result_dir = "results"
log_dir = ".omx/logs/local-runs"
pid_dir = ".omx/state/local-runs"
gpu_count = 1
```

Runner should launch long experiments as background local jobs:

```powershell
python scripts\research_supervisor.py launch --backend local --local-workdir . --local-result-dir results --local-log-dir .omx/logs/local-runs --local-pid-dir .omx/state/local-runs --run-id <run-id> --script-file <local-command-script>
```

Then watch with:

```powershell
python scripts\research_supervisor.py watch-backend --backend local --local-pid-dir .omx/state/local-runs --run-id <run-id> --local-result-dir results --local-glob "*.json" --poll-seconds 300 --max-polls 120
```

Local launch writes metadata to:

```text
.omx/state/local-runs/<run-id>.json
```

and logs to:

```text
.omx/logs/local-runs/<run-id>.log
```

### SSH backend
Use SSH mode when experiments run on a separate machine:

```toml
[execution]
backend = "ssh"
```

Populate:

```toml
[remote]
ssh_key = "..."
host = "..."
port = 22
remote_code_dir = "..."
remote_result_dir = "..."
gpu_count = 1
```

Runner should use the existing SSH supervisor commands:

```powershell
python scripts\research_supervisor.py launch-bash --ssh-key <ssh_key> --host <host> --port <port> --remote-workdir <remote_code_dir> --script-file <local-bash-script>
python scripts\research_supervisor.py watch --ssh-key <ssh_key> --host <host> --port <port> --screen-prefix <run-id> --remote-result-dir <remote_result_dir> --local-result-dir .omx/synced-results --local-glob "*.json"
```

### Runner state transitions
Runner and watch communicate through `.omx/state/run-state.json`. Treat this file as the source of truth for the current runner lifecycle.

When runner starts an experiment successfully, update the state like this:

```json
{
  "phase": "watch",
  "next_action": "watch",
  "run_id": "<run-id>",
  "execution_backend": "local",
  "execution_status": "running",
  "remote_status": "running"
}
```

For SSH, use `"execution_backend": "ssh"` and the same phase/status pattern. `remote_status` is retained for compatibility; do not introduce a separate local-only status field. Use `execution_status` for backend-neutral logic.

Watch writes a unified snapshot with:

```json
{
  "backend": "local",
  "watch_status": "running | synced | failed | timed_out | missing",
  "runner_active": true,
  "local_evidence_paths": {}
}
```

Autoloop uses `watch_status` to decide the next state:

- `synced`: evidence is available. If `runner_iteration >= runner_iteration_cap`, hand back to reader; otherwise continue runner.
- `running`: stay in `phase = "watch"`.
- `failed`, `timed_out`, or `missing`: return to runner with `next_action = "self_repair_and_retry"`.

When manually repairing runner state, keep these invariants:

- `phase` and `next_action` must agree:
  - active experiment: `phase = "watch"`, `next_action = "watch"`
  - evidence ready for reader: `phase = "reader"`, `next_action = "reader"`
  - runner retry needed: `phase = "runner"`, `next_action = "self_repair_and_retry"`
- Preserve `run_id` until the watch phase has consumed the matching launch metadata.
- Preserve or set `execution_backend` to `local` or `ssh`; never infer SSH just because fields are named `remote_*`.
- On failure, increment the repair counter through the existing loop code path when possible and write a concise `last_error`.
- `local_evidence_paths` must point only to local filesystem paths, even when evidence came from SSH sync.

Do not hardcode SSH behavior in runner or watch logic. Always read `execution.backend` or `run-state.json.execution_backend`.

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

### Local execution validation
Run this when `execution.backend = "local"`:

```powershell
New-Item -ItemType Directory -Force .omx | Out-Null
Set-Content -Path .omx\local-smoke.ps1 -Encoding UTF8 -Value "New-Item -ItemType Directory -Force results | Out-Null; Set-Content -Path results\local_smoke.json -Encoding UTF8 -Value '{`"ok`":true}'"
python scripts\research_supervisor.py launch --backend local --local-workdir . --local-result-dir results --local-log-dir .omx/logs/local-runs --local-pid-dir .omx/state/local-runs --run-id local-smoke --script-file .omx\local-smoke.ps1
python scripts\research_supervisor.py watch-backend --backend local --local-pid-dir .omx/state/local-runs --run-id local-smoke --local-result-dir results --local-glob "local_smoke.json" --poll-seconds 1 --max-polls 3
```

Expected result: final watch JSON includes `"backend": "local"` and `"watch_status": "synced"`.

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
