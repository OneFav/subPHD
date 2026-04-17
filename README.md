# sub-PHD Migration Starter

This package contains the minimal reusable sub-PHD runtime framework for moving into a new project.

## Included
- `index.md` (agent-facing initialization manual)
- `person_program.md`
- `agent_program.md`
- `research_agent.toml` (ships with empty SSH defaults)
- `start.bat` (fresh start)
- `resume.bat` (resume current state)
- `.subphd/` fresh runtime state
- `roles/reader/`
- `roles/runner/`
- `scripts/`
- lightweight `research/` placeholders for log files referenced by config

## Not included
- project-specific research code
- old runtime state/history from the source project
- old reports/prompts/commands/synced results
- project-specific experiment artifacts

## Typical migration steps
1. Copy or unzip this starter into the new repo.
2. Let the agent read `index.md` and initialize the starter.
3. Replace `person_program.md` with the new mission.
4. Add new project-specific code under `research/` if needed.
5. Start with:
   - `start.bat` for a new task
   - `resume.bat` to continue existing state

## Notes
- `index.md` is the intended first document for agent-guided setup.
- SSH support remains available, but the repository no longer ships with live SSH values.
- After initialization, the normal user-owned surface is `person_program.md` plus code under `research/`.
- `start.bat` resets `.subphd/state/*` before launching.
- `resume.bat` reuses current `.subphd/state/*`.
- The canonical runtime root is `.subphd/`.
