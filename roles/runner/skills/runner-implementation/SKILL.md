---
name: runner-implementation
description: Runner role helper for implementing and validating bounded changes in the repo working tree.
---

# Runner Implementation Skill

Use this role-local skill to keep execution concrete.
- Implement the current bounded assignment directly in the repo working tree.
- Validate with the smallest meaningful checks before handoff.
- Before the remote run ends, prune `remote_result_dir` so only the compact core artifacts remain for watch sync.
- Delete unnecessary intermediate/process files by default.
- Keep only the final decision/metrics/summary/manifest style artifacts unless the assignment explicitly requires more.
- If a large artifact might matter later, leave a small retained note about it rather than keeping the bulky file in `remote_result_dir`.
- For `expected_output` and `why`, write short plain-language lines that name the exact experiment, metric, file, or decision; avoid vague process-speak.
- Do not silently widen scope into open-ended redesign or exploration.
