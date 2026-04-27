# sub-PHD External Agent Protocol

This document defines a protocol for **optional external carrier-agent** skills that manage one or more sub-PHD projects from outside the sub-PHD runtime. Carrier agents include Hermes, OpenClaw, Claude Code, Codex, or any custom assistant with shell or remote-execution capability.

These skills are protocol/example skills. They are not Reader/Runner role skills, not a scheduler implementation, and not a registry service built into sub-PHD.

## Skill Layers

sub-PHD has three distinct skill layers:

1. **Internal role skills** under `roles/reader/skills/` and `roles/runner/skills/`.
   - These are composed into the Reader/Runner autoloop prompts.
2. **Built-in companion skills** under root `skills/`.
   - `subphd-run-disclosure` explains the current run window.
   - `subphd-program-refinement` helps refine `person_program.md`.
   - These remain the mandatory two-skill setup pair.
3. **Optional external carrier-agent skills** under root `skills/`.
   - `subphd-inspect`
   - `subphd-control`
   - `subphd-watch`
   - These help an outside assistant inspect, control, or watch multiple sub-PHD projects.

## External Assistant State

External carrier-agent state must live outside every sub-PHD project directory.

Default project manifest path:

```text
~/.subphd-agent/projects.json
%USERPROFILE%\.subphd-agent\projects.json
```

Default watch-rules path:

```text
~/.subphd-agent/watch-rules.json
%USERPROFILE%\.subphd-agent\watch-rules.json
```

Carrier agents may override these paths in their own configuration, but they must keep the same ownership rule: assistant state stays outside project directories.

## Project Manifest

The project manifest is the only supported way for these skills to resolve project paths. They must not scan disks or guess locations.

Minimum structure:

```json
{
  "schema_version": 1,
  "projects": [
    {
      "name": "transformer-ablation",
      "path": "C:/work/transformer-ablation",
      "description": "Ablation study for the transformer project",
      "tags": ["ml", "active"],
      "active": true
    }
  ]
}
```

Required root keys:

- `schema_version`
- `projects`

Required project-entry keys:

- `name`: unique user-facing project identifier.
- `path`: absolute or carrier-resolvable path to a sub-PHD project root.

Optional project-entry keys:

- `description`: human-readable context for semantic matching.
- `tags`: list of strings such as `active`, `ml`, or `paper`.
- `active`: boolean; when omitted, treat the project as active only if the carrier-agent policy says so.

“Manifest registration” always means writing an entry to this external assistant manifest, or to the carrier-agent override path. It never means editing this repository's `manifest.json`.

## Project Resolution Rules

1. Exact `name` match first.
2. For read-only inspect/watch requests, a carrier agent may use `tags` or `description` to narrow candidates.
3. If multiple candidates remain, ask the user to choose.
4. For destructive or lifecycle actions, require an exact project match.
5. Never scan the filesystem to discover projects.

## Allowed Read Targets

External skills may read the minimum needed subset of these files inside a project:

- `.subphd/state/run-state.json`
- `.subphd/state/agent-observability.json`
- `.subphd/state/research_watch_events.jsonl`
- `.subphd/logs/ai-worklog.md`
- `.subphd/reports/`
- `person_program.md`
- `agent_program.md` only when needed for context

The runtime state uses concrete fields such as:

- `last_error`
- `reader_iteration`
- `runner_iteration`
- `phase`
- `next_action`
- `execution_backend`
- `execution_status`

Do not invent a generic `iteration` state field.

## Control Entry Points

Start fresh:

```powershell
start.bat <max-runs> <hours>
python scripts\research_autoloop.py --workdir . --hours <H> --max-runs <N> --ignore-state
```

Resume:

```powershell
resume.bat <max-runs> <hours>
python scripts\research_autoloop.py --workdir . --hours <H> --max-runs <N>
```

There is no official `stop.bat` or stop subcommand in this pass. After explicit user confirmation and exact project resolution, a carrier agent may stop only the OS process it can identify as that project's `research_autoloop.py` process, preferably through graceful interrupt or termination from the host process manager. If the carrier cannot identify the exact process, it must give manual stop guidance instead of guessing.

Stopping is never implemented by editing `.subphd/state/*`.

## Project Creation

Project creation is a starter-copy plus external manifest-registration workflow:

1. Choose a target path and project name.
2. Confirm both with the user.
3. Copy a sub-PHD starter or migration pack into the target path.
4. Help draft `person_program.md` if requested.
5. Write `person_program.md` only after explicit user confirmation.
6. Add the project to the external assistant manifest only after explicit user confirmation.

Do not hand-write runtime state to create a project.

## Watch Rules

Watch rules belong to the carrier agent, not to sub-PHD.

Minimum structure:

```json
{
  "schema_version": 1,
  "rules": [
    {
      "id": "daily-active-summary",
      "scope": { "projects": "active" },
      "trigger": {
        "type": "schedule",
        "kind": "daily",
        "time": "09:00",
        "timezone": "Asia/Shanghai"
      },
      "action": {
        "skill": "subphd-inspect",
        "prompt": "Summarize all active projects briefly."
      },
      "cooldown_minutes": 60,
      "enabled": true
    }
  ]
}
```

Required root keys:

- `schema_version`
- `rules`

Required watch-rule keys:

- `id`: stable rule identifier.
- `scope`: project, tag, or active-project target.
- `trigger`: rule trigger object.
- `action`: what the carrier agent should do when triggered.
- `enabled`: boolean.

Optional watch-rule keys:

- `cooldown_minutes`
- `description`

`trigger.type` must be one of:

- `schedule`
- `event`
- `threshold`

Event sources include:

- `.subphd/state/run-state.json.last_error`
- `.subphd/state/run-state.json.reader_iteration`
- `.subphd/state/run-state.json.runner_iteration`
- `.subphd/logs/ai-worklog.md` append activity
- `.subphd/state/research_watch_events.jsonl`

Polling should be minutes- or hours-level, not every second.

## Prohibited Behavior

External carrier-agent skills must not:

- scan disks to find projects;
- directly write `.subphd/state/*`;
- silently overwrite `person_program.md`;
- pretend sub-PHD runtime stores or executes watch rules;
- claim a scheduler, registry API, or direct remote-control service exists in this pass;
- bind the protocol to Hermes, OpenClaw, SSH, Tailscale, Codex, or any specific notification backend.

## Capability Split

- `subphd-inspect`: read-only status, evidence, and summary work.
- `subphd-control`: start/resume, guarded stop guidance, and guarded project creation/registration.
- `subphd-watch`: carrier-side watch-rule management and event interpretation.
