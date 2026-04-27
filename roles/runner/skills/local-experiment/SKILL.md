---
name: local-experiment
description: Launch bounded runner experiments as local background jobs without SSH.
---

# Local Experiment

Use this skill when `research_agent.toml` selects `[execution].backend = "local"`.

- treat the current machine as the experiment host
- do not require SSH, SCP, `remote_code_dir`, or `remote_result_dir`
- launch long experiments as local background jobs through `scripts/research_supervisor.py launch --backend local`
- write compact result evidence into `local.result_dir`
- redirect stdout and stderr to the local run log path returned by the launcher
- after a successful launch, set `run-state.json` to `phase = "watch"` and `next_action = "watch"`
