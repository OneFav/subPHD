# sub-PHD 🎓🤖

> An AI grad student for your PhD: you assign the research, it does the work.

sub-PHD is a local reader/runner runtime for research loops. You keep the scientific judgment. The agent keeps the loop moving: reading, planning, coding, executing, and reporting.

## 🚀 The most convenient installation method
The best install path is not to guess the setup manually, but to **give this sentence directly to Codex**:

```text
Read https://github.com/OneFav/subPHD/blob/main/index.md and install the project locally.
```

You can also use the Chinese version:

```text
阅读 https://github.com/OneFav/subPHD/blob/main/index.md 并安装项目到本地
```

`index.md` is the installation contract for Codex. It tells Codex to:
- deploy the two repo-shipped sub-PHD skills
- initialize the starter
- run the required local validation

## 🧠 What sub-PHD is for
If you want an agent to keep research moving forward, but you do **not** want to hand away the actual scientific judgment, sub-PHD is designed for exactly that situation.

You are responsible for:
- defining the question
- deciding priorities
- reviewing evidence
- rewriting the research mission

The agent is responsible for:
- reading materials
- tightening the handoff
- writing code / running workflows
- producing reports
- continuing the next loop

It is not a normal AI copilot, and it is not a fully autonomous “AI scientist.” It is closer to **an AI grad student working under your direction**. 👨‍🎓🤖

## ⚡ Quick start
1. Clone this repository
2. Ask Codex to read `index.md` and complete the local installation
3. Edit `person_program.md`
4. Start with `start.bat` or the Python entrypoint

## ✍️ The file you really edit
### `person_program.md`

This is the main human task file. You usually edit it when you want to:
- change the research direction
- adjust priorities
- redefine success criteria
- move into the next stage

## 🧰 Two built-in skills
This starter ships two sub-PHD skills, and the docs assume you use them to understand project work and refine the mission.

### `subphd-run-disclosure`
Use this when you want Codex to explain:
- what the current run is doing
- which conclusions are actually supported
- what evidence exists
- how far the run has progressed relative to `person_program.md`

### `subphd-program-refinement`
Use this when you want Codex to help improve `person_program.md`:
- refine a still-vague next research direction
- propose a better rewrite of `person_program.md`
- keep the mission correct without freezing it too early

## 🔁 Runtime model
- `start.bat` = start a new big round
- `resume.bat` = continue the current state
- continuity is bounded by role-local windows instead of unbounded long context
- authoritative handoff has higher priority than generic recent reports

## 📦 Included
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

## 🚫 Not included
- your project-specific research code
- your previous runtime history
- your private SSH credentials

## 📝 Notes
- SSH support remains available, but the repository does not ship with your real configuration.
- To **understand what the project is doing**, prefer `subphd-run-disclosure`.
- To **revise `person_program.md`**, prefer `subphd-program-refinement`.
