---
name: subphd-watch
description: Use when an external carrier agent needs to define, list, update, cancel, or interpret carrier-side watch rules for sub-PHD project reminders, alerts, and periodic summaries.
---

# sub-PHD Watch

## Overview
`subphd-watch` is an **optional external carrier-agent** skill for managing reminder and alert rules around sub-PHD projects.

The rules are carrier-agent state. They are not sub-PHD runtime state, and this repository does not implement a scheduler in this pass.

## When to Use
Use when the user asks for:

- daily or weekly summaries;
- alerts when a project fails;
- reminders when a project has no progress for a threshold;
- listing, updating, or canceling existing watch rules.

Do not use when the user asks only for an immediate status summary; use `subphd-inspect` instead.

## Persistence
Default watch-rules paths:

```text
~/.subphd-agent/watch-rules.json
%USERPROFILE%\.subphd-agent\watch-rules.json
```

Carrier agents may override this path. Watch rules must stay outside every sub-PHD project directory.

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

Required root keys are `schema_version` and `rules`.

Required rule keys are:

- `id`
- `scope`
- `trigger`
- `action`
- `enabled`

Optional rule keys are:

- `cooldown_minutes`
- `description`

`trigger.type` must be one of:

- `schedule`
- `event`
- `threshold`

## Project Resolution
Resolve project targets through the external assistant manifest.

Default manifest paths:

```text
~/.subphd-agent/projects.json
%USERPROFILE%\.subphd-agent\projects.json
```

The watch skill must not scan disks. If a rule target is ambiguous, ask the user to clarify before registering the rule.

## Event Sources
A carrier agent may observe these project files:

- `.subphd/state/run-state.json.last_error`
- `.subphd/state/run-state.json.reader_iteration`
- `.subphd/state/run-state.json.runner_iteration`
- `.subphd/logs/ai-worklog.md` append activity
- `.subphd/state/research_watch_events.jsonl`

Do not invent a generic `iteration` field.

## Rule Operations
### Add
Translate the user's natural language into a concrete rule, then read it back in plain language before registration.

Example confirmation:

> I will check all active projects every weekday at 09:00 Asia/Shanghai and send a short summary through this carrier agent's notification channel. Is that correct?

### List
Show rule `id`, scope, trigger, action, cooldown, and enabled status.

### Update
Require a rule `id` or an unambiguous rule description. Show the changed rule before saving.

### Remove
Require a rule `id` or an unambiguous rule description. Confirm before deletion.

## Cooldown and Conflict Rules
- Avoid duplicate alerts for the same event within a short period.
- Prefer minutes- or hours-level polling, not seconds-level polling.
- If a new rule overlaps existing rules, propose a merge instead of stacking noisy alerts.

## Failure Behavior
- If the watch-rules file is missing, offer to create it in the carrier-agent state path.
- If the project manifest is missing, explain that watches need the manifest to resolve projects.
- If a watched project path becomes invalid, disable or report the rule instead of repeatedly failing silently.

## Boundaries
- Do not write watch rules into any sub-PHD project directory.
- Do not mutate `.subphd/state/*`.
- Do not claim sub-PHD runtime stores or executes watch rules.
- Do not assume any specific notification platform or scheduler backend.
- Use `subphd-inspect` for summaries and `subphd-control` only for explicit user-approved lifecycle actions.
