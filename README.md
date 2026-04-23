# sub-PHD Migration Starter

This package contains the minimal reusable sub-PHD runtime framework for moving into a new project.

## Included
- `index.md` (agent-facing initialization manual)
- `skills/subphd-run-disclosure/`
- `skills/subphd-program-refinement/`
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
2. Let the agent read `index.md`, deploy the two repo-shipped sub-PHD skills, and initialize the starter.
3. Use `subphd-run-disclosure` when you want Codex to explain the current run window and project progress.
4. Use `subphd-program-refinement` when you want Codex to improve or rewrite `person_program.md`.
5. Add new project-specific code under `research/` if needed.
6. Start with:
   - `start.bat` for a new task
   - `resume.bat` to continue existing state

## Notes
- `index.md` is the intended first document for agent-guided setup.
- SSH support remains available, but the repository no longer ships with live SSH values.
- After initialization, the normal user-owned surface is `person_program.md` plus code under `research/`.
- The recommended way to understand current project work is to use `subphd-run-disclosure`.
- The recommended way to revise `person_program.md` is to use `subphd-program-refinement`.
- `start.bat` resets `.subphd/state/*` before launching.
- `resume.bat` reuses current `.subphd/state/*`.
- The canonical runtime root is `.subphd/`.
- Continuity uses role-local windows with a short resume budget rather than unbounded same-chat history.
- The authoritative handoff under the reports root is the first continuity source before generic recent reports.
