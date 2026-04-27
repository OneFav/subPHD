---
name: local-watch
description: Monitor local background experiment metadata, process state, logs, and result files.
---

# Local Watch

Use this skill when `research_agent.toml` selects `[execution].backend = "local"` and the loop is monitoring a local run.

- watch local run metadata, process status, logs, and result files
- use `scripts/research_supervisor.py watch-backend --backend local`
- treat `watch_status = "synced"` as local evidence ready for reader or runner review; no remote sync is needed
- report failures as local process, log, heartbeat, or result problems, not SSH problems
- keep `local_evidence_paths` pointing only to local files
