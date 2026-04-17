---
name: reader-handoff
description: Reader role helper for clarifying next bounded objectives from repo-local runtime evidence.
---

# Reader Handoff Skill

Focus on turning current runtime evidence into the next bounded assignment for runner.
- Prefer reading runtime state, reports, observability, and repo-local artifacts first.
- Update `agent_program.md` when the next implementation lane needs a tighter contract.
- When the next runner turn is remote, define the compact core artifact set that should remain in `remote_result_dir` and let runner delete non-essential process files before watch sync.
- Write `expected_output` and `why` in plain language, naming the concrete experiment, metric, file, or decision rather than vague process wording.
- End with a clear handoff rather than open-ended brainstorming.
