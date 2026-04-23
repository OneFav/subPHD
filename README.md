# sub-PHD

> An AI grad student for your PhD: you assign research, it does the work.

sub-PHD is a local reader/runner runtime for research loops. You keep the scientific judgment. The agent keeps the loop moving: reading, planning, coding, running, and reporting.

## Best install method
The most convenient and reliable way to install this project is to let Codex do it for you.

Give Codex this exact instruction:

```text
Read https://github.com/OneFav/subPHD/blob/main/index.md and install the project locally.
```

That `index.md` file is the agent-facing setup contract. It tells Codex how to deploy the shipped skills, initialize the starter, and validate that the runtime works.

## What sub-PHD is for
Use sub-PHD when you want an agent to run the repetitive part of a research loop while you stay in charge of:
- choosing the question
- deciding what matters
- reviewing evidence
- rewriting the mission

It is not a generic AI copilot and not a fully autonomous "AI scientist". It is closer to an AI grad student working under your direction.

## Quick start
1. Clone the repo.
2. Ask Codex to read `index.md` and install the project locally.
3. Edit `person_program.md`.
4. Start the loop with `start.bat` or the Python entrypoint.

## The only file you normally edit
`person_program.md`

That is the main human-owned mission file. You update it when you want to:
- change the research direction
- tighten priorities
- redefine success criteria
- start a new stage of work

## Two built-in skills
This starter ships two sub-PHD skills and the docs assume you use them.

### `subphd-run-disclosure`
Use this when you want Codex to explain:
- what the current run window is doing
- what conclusions are supported
- what evidence exists
- how complete the run is versus `person_program.md`

### `subphd-program-refinement`
Use this when you want Codex to:
- refine a vague next research direction
- propose a better rewrite of `person_program.md`
- keep the mission correct without making it too rigid too early

## Runtime model
- `start.bat` = fresh big-round start
- `resume.bat` = continue current state
- continuity is bounded by role-local windows
- authoritative handoff artifacts outrank generic recent reports

## Included
- `index.md`
- `skills/subphd-run-disclosure/`
- `skills/subphd-program-refinement/`
- `person_program.md`
- `agent_program.md`
- `research_agent.toml`
- `start.bat` / `resume.bat`
- `.subphd/`
- `roles/`
- `scripts/`

## Not included
- your project-specific research code
- your old runtime history
- your private SSH credentials

## Notes
- SSH support is available, but the repo does not ship with your live credentials.
- The recommended way to understand project work is `subphd-run-disclosure`.
- The recommended way to revise `person_program.md` is `subphd-program-refinement`.
