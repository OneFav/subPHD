# sub-PHD 🎓🤖

English | [中文](README.zh-CN.md)

> An AI grad student for your PhD: "This is my student. I can work it like a mule."

sub-PHD is a lightweight local multi-agent framework for "human-AI collaboration + auto-research." You periodically hold "group meetings" with the agent to express your research thinking, needs, and adjustments, and the agent keeps trying things and running experiments according to **your line of thought**, like a grad student.

<img src="image/README.zh-CN/1777191565693.png" alt="sub-PHD overview" width="924" />

## 🚀 How to install

From an individual user's perspective, agents are great for learning new tools, methods, and frameworks. So the install path I **most recommend** is to **give the following sentence directly to Codex**:

```text
Read https://github.com/OneFav/subPHD/blob/main/index.md and install the project locally.
```

This project is specifically adapted for agents. `index.md` is the installation contract for Codex. It tells Codex to:

- deploy the two repo-shipped sub-PHD skills: 1. `subphd-run-disclosure`, used to summarize what each long-running round actually did. 2. `subphd-program-refinement`, used to help revise `person_program.md` for the next round of work.
- ask you for the necessary configuration details.
- run the required local validation and complete a minimal round successfully.

Or, you can install it manually:

1. clone this repository
2. let Codex read `index.md` and run through the tests
3. edit `person_program.md`
4. start it with `start.bat` or the Python entrypoint

Note: because Claude Code burns through usage too quickly, while the Codex subscription is much more generous, this project currently supports only `codex exec`. You can also log into the Codex CLI via API. The recommended model is `deepseek v4`.

## 🧠 What problem sub-PHD is trying to solve

AI research tools on the market over the past two years roughly fall into two camps.

The first camp treats AI as an **extension** of the human. Copilot helps you write code, Cursor helps you fix bugs, and various research agents help you read papers. These tools are all useful, but they share one assumption: **you are still the one doing the work**, and AI is only an extension of you. The problem is that the hardest part of being a PhD student is not just "doing work." The hardest part is that you have to do the work, plan the work, supervise whether you're doing the work well, and then lie awake late at night wondering whether any of this work means anything at all. One person ends up playing **four roles at once: PI, postdoc, PhD student, and personal therapist for their own advisor-induced stress**. No matter how many helpful "tools" you add, they do not truly free that person.

The second camp treats AI as a **replacement** for the human. These are the projects you may have seen over the past two years claiming things like "AI scientist writes the whole paper automatically" or "end-to-end autonomous research agent." I care a lot about these projects too, but honestly, so far they still do not solve the real problems I face as an actual PhD student. They can run benchmarks, reproduce existing pipelines, and push forward problems inside pre-defined domains. But a PhD student's research is **never a track someone else laid out in advance: you are solving your own concrete problem, pushing your own specific idea in your own field, and dealing with your advisor, your collaborators, and a pile of constraints that only you truly know**. Fully autonomous agents still struggle to understand those things deeply, and they cannot really do that part for you. Maybe they can imitate "doing research," and sometimes do it impressively well, but they cannot enter the specific context of your PhD life and solve *your* problem well. The result is a flashy demo that is useless when it comes to your actual dissertation.

So sub-PHD chooses a third path: not an extension of the human, not a replacement for the human, but **the human's student**. Its design does one simple but crucial thing: it flips the positions of the human and the agent. You are no longer the PhD student being pushed. You are the advisor. The agent is the PhD student. It listens, takes pressure well, does not spiral, does not emotionally collapse because of one sentence from the advisor, and does not text you at midnight saying "Professor, I don't think I'm cut out for research." And you stand in the one place only a human can stand: the person who decides direction, judges results, and takes responsibility for the research. 👨‍🎓🤖

## ✍️ How to use it

1. Use `subphd-program-refinement` to interact with the LLM, clarify what you actually want to do right now, and generate a trustworthy `person_program.md`.
2. Double-click `start.bat`, or run `python scripts/research_autoloop.py --hours 4 --max-runs 30 --ignore-state` in the command line.
   Here, `4` is the maximum duration and `30` is the maximum number of runs; adjust them freely based on your experiment size.
3. Use `subphd-run-disclosure` to inspect the current run interactively, understand what this round did, what it concluded, and how far it is from `person_program.md`.
4. Decide what to do next based on the run results: continue with `resume.bat`, or go back to step 1 and revise `person_program.md`.

## 🧰 Built-in skills

This starter ships with two sub-PHD skills, and the documentation assumes you will use them to understand what the project is doing and tighten the mission.

### `subphd-run-disclosure`

Use it when you want Codex to explain questions like:

- what the current run is doing
- which conclusions are actually supported by evidence
- what evidence exists
- how far the current progress is relative to `person_program.md`

### `subphd-program-refinement`

Use it when you want Codex to help improve `person_program.md`:

- tighten a next-step research direction that is still vague
- propose a better rewrite of `person_program.md`
- make the mission more correct without freezing it too early

## 🔁 Runtime model

- `start.bat` = start a new major round
- `resume.bat` = continue the current state
- continuity is controlled by role-local windows instead of accumulating unbounded long context
- authoritative handoff has higher priority than generic recent reports

## 📦 Included

- `index.md`: the initialization entry contract for this starter. The agent reads it first, then follows its flow to install the repo-shipped skills, ask the minimum configuration questions, fill in the framework files, and run a smoke check.
- `skills/subphd-run-disclosure/`: the skill for explaining "what this whole run actually did." It is instructed to read reports, synced results, and `run-state.json` under `.subphd/` first, then produce an evidence-oriented run brief for the human.
- `skills/subphd-program-refinement/`: the skill for gradually turning a vague research direction into a candidate rewrite of `person_program.md`. It emphasizes one-question-at-a-time refinement, producing a candidate version first, and only writing it after user confirmation.
- `person_program.md`: the human-maintained mission anchor file. In the codebase it is treated as a human-owned control document that defines the current mission, priorities, reader/runner responsibilities, and success conditions for this round.
- `agent_program.md`: the framework-maintained execution strategy file. The reader updates it directly during the loop, tightening the current strategy and next handoff into an executable task boundary for the runner.
- `research_agent.toml`: the top-level runtime configuration. It defines the default model, time and run limits, SSH remote execution parameters, and the artifact paths for `person_program.md`, `.subphd/state/*`, logs, and synced results.
- `start.bat` / `resume.bat`: the Windows entrypoints. Both launch `research_dashboard.py` and `research_autoloop.py`; `start.bat` first calls `reset_runtime_state(...)` and starts a fresh round with `--ignore-state`, while `resume.bat` keeps the existing state and continues.
- `.subphd/`: the canonical runtime root of the framework. The code creates directories such as `state/`, `logs/`, `reports/`, `prompts/`, `commands/`, `synced-results/`, and `autoloop/` here to store loop state, observations, reports, prompts, and synced results.
- `roles/`: the role-surface definitions for Reader / Runner. `research_agent_cli.py` reads the `AGENTS.md` files and role-private `skills/` here, then composes their constraints, responsibilities, and activatable capabilities into each role prompt.
- `scripts/`: the main implementation directory of the framework. Core pieces include `research_agent_cli.py` (single-role launch and prompt assembly), `research_autoloop.py` (reader/runner/watch auto-loop), `research_dashboard.py` (local monitoring dashboard), and `research_supervisor.py` (SSH remote launch, polling, and result sync).

## 🔭 Future plans

1. Provide a version that **does not depend on SSH**, aimed at users who mainly run experiments directly on a local machine, lowering the initial setup barrier and making sub-PHD easier to use in single-machine research scenarios.
2. Add a new agent beyond reader and runner: **reviewer**. On one hand, it helps the reader make task decomposition and iteration align better with `person_program.md`; on the other hand, in non-algorithmic research settings such as data investigation, literature synthesis, mathematical calculation, or theoretical derivation, the reviewer defines evaluation methods and success criteria so that sub-PHD can adapt to more kinds of research work.
3. This part needs community help: for different domain tasks, gradually build up `AGENTS.md` and `skills/` libraries adapted to different roles, so the framework is not limited to one research style but can be reused across more disciplines.
4. A mysterious update is coming. Stay tuned.

   Everyone is welcome to join the sub-PHD group chat~

   <img src="image/README.zh-CN/1777192938397.jpg" alt="sub-PHD group chat" width="574" />
