---
name: subphd-inspect
description: Use when an external carrier agent needs read-only status, evidence, or cross-project summaries for one or more sub-PHD projects resolved through the external project manifest.
---

# sub-PHD Inspect

## Overview
`subphd-inspect` is an **optional external carrier-agent** skill. It helps an outside assistant explain one or more sub-PHD projects without mutating them.

It is read-only. It does not start, stop, resume, create, repair, or rewrite projects.

## When to Use
Use when the user asks questions such as:

- "Where is transformer-ablation now?"
- "How did all active projects progress today?"
- "Which project is stuck the longest?"
- "Give me a weekly report."
- "Which ML project looks most promising?"

Do not use when the user wants to:

- start, resume, stop, or create a project;
- register watch rules;
- rewrite `person_program.md`;
- directly modify `.subphd/state/*`.

## Required Input
Resolve projects through the external assistant manifest.

Default manifest paths:

```text
~/.subphd-agent/projects.json
%USERPROFILE%\.subphd-agent\projects.json
```

Carrier agents may use an override path, but they must not scan disks to find projects.

Minimum manifest structure:

```json
{
  "schema_version": 1,
  "projects": [
    {
      "name": "transformer-ablation",
      "path": "C:/work/transformer-ablation",
      "description": "Ablation study",
      "tags": ["ml", "active"],
      "active": true
    }
  ]
}
```

Required project-entry keys are `name` and `path`. Optional keys are `description`, `tags`, and `active`.

## Project Resolution
1. Prefer exact `name` match.
2. For read-only queries, use `tags` and `description` only to narrow candidates.
3. If the user gives no project, default to active projects and say that you used that default.
4. If multiple candidates remain, ask the user to choose.
5. Never scan the filesystem to guess project paths.

## Evidence Order
Read the minimum needed evidence set.

1. Current runtime state:
   - `.subphd/state/run-state.json`
2. Timeline and dashboard-style context:
   - `.subphd/state/agent-observability.json`
   - `.subphd/logs/ai-worklog.md`
3. Formal outputs:
   - `.subphd/reports/`
   - `.subphd/synced-results/` if present
4. Mission context:
   - `person_program.md`
   - `agent_program.md` only if needed

Important state fields include `phase`, `next_action`, `last_error`, `reader_iteration`, `runner_iteration`, `execution_backend`, and `execution_status`. Do not invent a generic `iteration` field.

## Output Contract
Answer at the user's requested granularity.

- For quick status: 2-5 bullets.
- For daily or weekly reports: group by project and highlight evidence, blockers, and next likely action.
- For cross-project comparison: state the comparison criteria and uncertainty.

Separate:

- facts read from files;
- inferences based on those facts;
- uncertainty caused by missing or weak evidence.

## Failure Behavior
- If the manifest is missing, explain that the carrier agent needs `~/.subphd-agent/projects.json` or `%USERPROFILE%\.subphd-agent\projects.json`; offer to help draft one, but do not scan disks.
- If a project path is invalid, name the project and path and report which expected files are missing.
- If state files are missing, degrade confidence instead of inventing status.

## Boundaries
- Read-only.
- No direct writes to sub-PHD project files.
- No direct writes to `.subphd/state/*`.
- No `person_program.md` edits.
- No carrier-specific assumptions about SSH, Tailscale, notifications, or LLM backend.
