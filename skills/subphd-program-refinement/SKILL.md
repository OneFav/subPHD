---
name: subphd-program-refinement
description: Use when the user gives a vague research direction for a new sub-PHD run and wants one-question-at-a-time refinement that is correct but not overly precise, leading to a candidate rewrite of person_program.md before any final write.
---

# sub-PHD Program Refinement

## Overview
This skill is a **research-program refinement workflow**, not ordinary brainstorming. Its job is to turn a vague human instruction for the next automated research run into a better mission draft for `person_program.md`.

**Core principle:** for frontier research, the target is **correct but not overly precise**. The mission should be directionally right, evidence-aware, and flexible enough to survive failure, redesign, and unexpected discovery.

## When to Use
Use when:
- the user gives a vague new research direction for the next automated run
- the user wants iterative questioning before changing the research mission
- the end goal is to rewrite `person_program.md`
- the current `person_program.md` feels stale, too narrow, too confused, or misaligned with the newest evidence
- the user wants stronger mission refinement than a casual brainstorm, but not a full implementation plan

Do **not** use when:
- the user already gave an exact replacement text for `person_program.md`
- the user wants a concrete next experiment plan
- the user wants detailed implementation steps, exact architecture names, hyperparameters, or file-level edits
- the task is only about summarizing the current run
- the task is only about editing `agent_program.md` without changing the research mission

## Why This Is Different From Brainstorming
Ordinary brainstorming usually rewards more specificity. That is often good for product or implementation work, but too much specificity is harmful for uncertain research.

In research:
- the next hypothesis may fail
- the most important bottleneck may change after one run
- useful progress often comes from refining the **direction**, not locking the exact solution
- the mission should stay useful even if the next experiment disappoints

So this skill optimizes for:
- **directional correctness**
- **clear mission logic**
- **explicit reasons for the next run's main tasks**
- **room for uncertainty**

It should avoid overcommitting to one exact mechanism, one exact benchmark pairing, or one exact explanation unless the evidence already justifies that level of commitment.

## Output Target
This workflow should **not** directly overwrite the program on first pass.

It should first produce:
- a **candidate rewrite** of `person_program.md`
- and, if clarity is sufficient, an optional **candidate rewrite** of `agent_program.md`

Only after explicit user confirmation should it actually write the final file changes.

## Questioning Style
Ask **one question at a time**.

Prefer asking **"why"** repeatedly when the surface request is still vague. In uncertain research work, repeated "why" questions are often the best way to uncover the human's real intent instead of overfitting to the first concrete-looking wording.

Each question should help do one of these:
1. clarify the real mission shift
2. identify what should remain stable from the old `person_program.md`
3. identify what should be dropped or deprioritized
4. surface the most important uncertainty the next run should resolve
5. distinguish between:
   - long-term scientific objective
   - near-term run objective
   - evidence needed to justify another mission rewrite later

Do not ask for implementation detail too early.
Do not optimize for perfect precision.
Do not exhaust the user with broad speculative branching.

## Stop Condition
Stop questioning when the following is clear enough:
- **the next run's major tasks**
- **why those tasks matter**

That is the readiness condition. The skill does **not** need a full implementation plan before drafting the new program.

## What Good Refinement Looks Like
A good refinement produces a candidate `person_program.md` that answers:
- What is the current research question now?
- What has changed since the previous mission?
- What should the next run try to learn, not merely do?
- What are the next run's main tasks?
- Why are those tasks the right ones now?
- What evidence would count as encouraging, discouraging, or rewrite-triggering?

## Main Rewrite Strategy
This skill should behave as a **research-task reorganizer**, not a conservative patcher.

Default rewrite posture:
1. **rewrite the `Human's Understanding` section as a whole when needed**
2. then align the rest of `person_program.md` to:
   - the new human understanding
   - the unfinished mission from the prior run

This means the skill may preserve deep scientific intent while still reorganizing the structure aggressively when the mission logic has shifted.

## What To Preserve
When possible, preserve:
- the deepest long-term scientific objective
- valid benchmark constraints
- important non-goals
- lessons already learned from prior failure

Only preserve old wording when it still supports the new mission logic.

## What To Rewrite Aggressively
Rewrite aggressively when the old program is:
- chasing a lane whose evidence is no longer strong enough
- too architecture-specific too early
- too vague to guide the next run
- too optimistic relative to actual evidence
- mixing long-term ambition with short-term execution in a confusing way

## Correct But Not Overly Precise
Use these rules when drafting the next mission.

### Prefer
- "focus on a small set of plausible mechanism families"
- "choose the sharpest live benchmark surface"
- "seek evidence that can distinguish continue vs redesign"
- "preserve frozen benchmark constraints unless evidence justifies a change"
- "define the next run by the main tasks and their reasons"

### Avoid
- hard-coding one exact architecture too early
- pretending the next run already knows the winning mechanism
- locking the mission to one narrow interpretation of success
- writing a program that becomes obsolete after one failed experiment
- turning the mission rewrite into a hidden experiment plan

## Rewrite Criteria
Draft the candidate rewrite only after these are clear enough:

1. **Mission shift**
   - what changed since the previous version
2. **Stable core**
   - what still remains true and should stay
3. **Next-run major tasks**
   - what the next large run should mainly do or learn
4. **Why these tasks**
   - why these are the right tasks now
5. **Evaluation logic**
   - what evidence would count as encouraging, discouraging, or rewrite-triggering
6. **Flexibility guardrail**
   - what must stay intentionally open because the next run is likely to reveal surprises

If these are not clear yet, keep interviewing.

## Rewrite Protocol
Once the mission is clear enough:

1. read the current `person_program.md`
2. identify the stable core vs the parts that need reorganization
3. produce a **candidate rewrite** of `person_program.md`
4. focus the strongest restructuring on the `Human's Understanding` section
5. align the rest of `person_program.md` to the new understanding and unfinished mission
6. if clarity is high enough, produce an optional candidate rewrite of `agent_program.md`
7. explain what changed and why
8. ask for explicit confirmation before applying file writes

## Recommended Structure For The Candidate person_program.md
The candidate rewrite should usually contain:
- current mission
- what remains true
- what changed
- next-run major tasks
- why those tasks matter now
- what reader should optimize for
- what runner should optimize for
- success signals
- failure / rewrite signals
- explicit non-goals

## Common Mistakes
### Mistake: treating research mission refinement like product scoping
Fix: optimize for directional correctness and evidence sensitivity, not maximum specification density.

### Mistake: asking only "what" and not enough "why"
Fix: use repeated "why" questions to recover real intent under uncertainty.

### Mistake: making the mission too narrow
Fix: leave room for the next run to fail without making the whole program immediately useless.

### Mistake: turning the rewrite into a hidden experiment plan
Fix: define major tasks and reasons, not fine-grained execution steps.

### Mistake: rewriting only the wording, not the logic
Fix: explicitly reorganize the `Human's Understanding` section and align the rest to it.

### Mistake: directly editing files before the user approves
Fix: always produce a candidate rewrite first, then wait for confirmation.

## Quick Reference
| Situation | Action |
|---|---|
| User gives a vague new direction | Start one-question refinement |
| Surface request sounds too concrete too early | Ask "why" before asking implementation detail |
| Old mission is partly valid | Preserve the stable core, reorganize the shifted mission logic |
| Latest evidence is mixed | Write a mission that tests the uncertainty instead of pretending it is resolved |
| Need to stop | Stop when the next run's major tasks and why they matter are clear enough |
| Clarity is sufficient | Produce candidate `person_program.md`, and optionally candidate `agent_program.md` |
| User approves | Apply the rewrite |
