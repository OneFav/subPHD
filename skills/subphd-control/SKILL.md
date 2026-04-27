---
name: subphd-control
description: Use when an external carrier agent needs to start, resume, guarded-stop, or create/register sub-PHD projects through official entrypoints and explicit confirmation gates.
---

# sub-PHD Control

## Overview
`subphd-control` is an **optional external carrier-agent** skill for lifecycle operations around sub-PHD projects.

It controls projects only through official sub-PHD entrypoints or through carrier-side process management after explicit confirmation. It must never directly edit `.subphd/state/*`.

## When to Use
Use when the user asks to:

- start a project fresh;
- resume a project;
- stop a running project;
- create a new sub-PHD project;
- add a created project to the external assistant manifest.

Do not use when the user only wants a status summary; use `subphd-inspect` instead.

## Required Input
Resolve target projects through the external assistant manifest.

Default manifest paths:

```text
~/.subphd-agent/projects.json
%USERPROFILE%\.subphd-agent\projects.json
```

“Manifest registration” means writing a project entry to this external assistant manifest or a carrier-agent override path. It does not mean editing this repository's `manifest.json`.

## Project Resolution
Lifecycle actions require exact target resolution.

- Prefer exact `name` match.
- Do not use fuzzy matching for destructive or write-adjacent actions.
- If multiple candidates match, ask the user to choose.
- Never scan disks to discover projects.

## Supported Actions

### Start Fresh
Use one of the official entrypoints from the project root:

```powershell
start.bat <max-runs> <hours>
python scripts\research_autoloop.py --workdir . --hours <H> --max-runs <N> --ignore-state
```

### Resume
Use one of the official entrypoints from the project root:

```powershell
resume.bat <max-runs> <hours>
python scripts\research_autoloop.py --workdir . --hours <H> --max-runs <N>
```

### Stop
There is no official `stop.bat` or stop subcommand in this pass.

After explicit user confirmation and exact project resolution, the carrier agent may stop only the OS process it can identify as that exact project's `research_autoloop.py` process. Prefer a graceful interrupt or termination mechanism provided by the host process manager.

If the carrier agent cannot identify the exact process, it must provide manual guidance instead of guessing.

Stopping must never be represented as a direct `.subphd/state/*` edit.

### Create Project
Project creation is a starter-copy plus external manifest-registration workflow:

1. Propose project name and target path.
2. Ask for explicit confirmation.
3. Copy a sub-PHD starter or migration pack into the target path.
4. Help draft `person_program.md` if requested.
5. Write `person_program.md` only after explicit user confirmation.
6. Ask before adding the project to the external assistant manifest.
7. Register the project only in `~/.subphd-agent/projects.json`, `%USERPROFILE%\.subphd-agent\projects.json`, or the carrier-agent override manifest.

## Confirmation Gates
Require explicit user confirmation before:

- stopping a running process;
- creating a project directory;
- overwriting any existing path;
- writing or replacing `person_program.md`;
- adding or changing an external manifest entry;
- resetting state through `start.bat` or `--ignore-state` if the user did not clearly ask for a fresh start.

## Post-Action Verification
After start or resume:

- check that the command launched or completed as expected;
- read `.subphd/state/run-state.json` if available;
- look for a live `research_autoloop.py` process when the carrier environment permits;
- report command, project, duration, and evidence.

After guarded stop:

- verify the exact process is no longer active when possible;
- report what was stopped and what could not be verified.

After project creation:

- verify the target directory exists;
- verify expected files such as `index.md`, `research_agent.toml`, `person_program.md`, and `scripts/research_autoloop.py` exist;
- verify the external manifest entry was written if the user approved registration.

## Failure Behavior
- If the manifest is missing, explain how to create `~/.subphd-agent/projects.json` or `%USERPROFILE%\.subphd-agent\projects.json`.
- If a project path is invalid, stop before running commands.
- If a command fails, report the command, exit code, and useful stdout/stderr summary.
- Never pretend a lifecycle action succeeded without verification.

## Boundaries
- No direct `.subphd/state/*` edits.
- No hidden disk scan project discovery.
- No automatic `person_program.md` write.
- No assumption that SSH, Tailscale, Hermes, OpenClaw, Codex, or any notification backend exists.
