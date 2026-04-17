# sub-PHD Migration Pack

This template is a reusable starter pack for the local sub-PHD runtime.

## What is already initialized
- `index.md` is available as the agent-facing initialization surface
- `person_program.md` is a valid starter template
- `agent_program.md` is initialized
- `.subphd/state/*.json` starts from a fresh `reader` state
- `sub-PHD` observability starts empty
- `research_agent.toml` ships with empty SSH defaults ready for agent-guided setup
- project-local `roles/reader` and `roles/runner` surfaces are present
  - no separate workspace directory is required; agents work directly in the repo tree

## What you usually need to change in a new project
1. Let the agent read `index.md` and perform initialization
2. Edit `person_program.md`
3. If the new project uses SSH / remote execution, update:
   - `remote_code_dir`
   - `remote_result_dir`
4. If needed, adjust project-specific files under `research/`

## Fresh start commands
```bash
python scripts/research_autoloop.py --workdir . --ignore-state
python scripts/research_dashboard.py --workdir .
```

## Notes
- `--ignore-state` resets the loop to a fresh task start (`reader`) and clears the dashboard timeline.
- `agent_program.md` can remain auto-managed; the human should usually only need to maintain `person_program.md` and project code under `research/`.
