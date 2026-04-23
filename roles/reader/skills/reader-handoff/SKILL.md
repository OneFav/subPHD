---
name: reader-handoff
description: Reader role helper for turning shared runtime evidence into the next bounded objective.
---

# Reader Handoff

Use this project-local role skill to keep reader work concrete:

 - inspect the current authoritative handoff first, then current authoritative artifacts, and only then fall back to generic reports/archive if needed
- tighten `agent_program.md` into a runner-ready assignment
- when the next runner turn is remote, define the compact core artifact set that should remain in `remote_result_dir`
- instruct runner to delete non-essential process files before watch sync whenever those files do not need to come back locally
- write `expected_output` and `why` in plain language, naming the concrete experiment, metric, file, or decision rather than vague process wording
- prefer bounded objectives over abstract future planning
