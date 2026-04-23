---
name: subphd-run-disclosure
description: Use when the user wants an evidence-first, staged briefing of the current sub-PHD run window, including what the run did, progress versus person_program.md, which propositions have meaningful conclusions, what evidence supports them, and plain-language explanations of new concepts.
---

# sub-PHD Run Disclosure

## Overview
This skill turns one continuous sub-PHD run window into a readable briefing instead of a raw log dump. It should first give a compact overall summary, then expand only the sections the user asks for.

**Core principle:** Prefer formal evidence over narration. If the evidence is thin, say so directly instead of pretending a conclusion is stronger than it is.

## When to Use
Use when the user wants to understand the **current sub-PHD run window** rather than a single reader/runner hop.

Typical triggers:
- "What did this run actually do?"
- "How complete is this compared with person_program.md?"
- "Which propositions have real conclusions?"
- "What evidence supports those conclusions?"
- "Explain this new concept in plain language"
- "Give me the high-level summary first, then let me ask questions"

Do **not** use when:
- The user wants the complete multi-run project history
- The user wants automatic rewriting of `person_program.md`
- The user wants the next experiment plan generated automatically
- The user wants a dashboard replacement instead of a conversational briefing
- The user needs external search beyond current local project evidence

## Evidence Order
Always prefer sources in this order:

1. Formal reports and structured result artifacts
   - `.subphd/reports/research-agent-report-*.md`
   - `.subphd/synced-results/*`
   - `.subphd/state/run-state.json`
2. Supporting runtime context
   - `.subphd/state/agent-observability.json`
   - `.subphd/reports/agent-observability-*.json`
   - `.subphd/logs/ai-worklog.md`
3. Secondary repository context only if needed to interpret the above
   - `person_program.md`
   - `agent_program.md`

If the higher-priority evidence is missing or weak, say that clearly.

## Reporting Unit
Treat "this run" as **one continuous large run window** (for example a 1h or 8h session), not one `reader -> runner` pass.

Anchor the summary on the currently active run window by using:
- current `run-state.json`
- recent formal reports in `.subphd/reports/`
- recent synced result artifacts associated with the same continuous run

## First Response Contract
The first response should be short and decision-oriented. It must answer these four questions:

1. **What was this run mainly doing?**
2. **What propositions currently have the strongest conclusions?**
3. **What evidence supports those propositions?**
4. **How complete is this run relative to `person_program.md`?**

Use this structure:

### 1) Run Summary
- 2-4 sentences
- Focus on the main thread of work, not every micro-step

### 2) Completion vs `person_program.md`
Provide a **semi-structured score breakdown first**, then a coarse recommendation.

Use a breakdown such as:
- Goal alignment
- Evidence quality
- Decisive conclusions reached
- Remaining uncertainty

Then add a coarse recommendation:
- **Continue**
- **Continue, but watch for rewrite pressure**
- **Consider rewriting `person_program.md`**

Bias: if completion looks decent but evidence is still somewhat weak, lean **slightly optimistic**, but never hide the weakness.

### 3) Concluded Propositions
List only propositions with meaningful conclusions in this run window.
For each proposition, include:
- proposition statement in plain language
- current status: supported / weakened / mixed / still unclear
- confidence: low / medium / high

Do **not** force weak evidence into a strong conclusion.

### 4) Evidence
For each concluded proposition, name the main evidence sources:
- report
- metric/result artifact
- comparison against prior/baseline method
- explicit uncertainty if evidence is partial

## Progressive Disclosure Protocol
After the initial summary, expand only the section the user asks for.

Suggested expansion sections:
- **goal** — what the run was trying to accomplish
- **completion** — scoring rationale against `person_program.md`
- **claims** — each proposition and what changed
- **evidence** — deeper evidence chain for each proposition
- **concepts** — plain-language explanation of new concepts/terms
- **timeline** — high-level sequence of what happened in the run window
- **risks** — what remains unresolved

When the user asks a follow-up, stay inside that section first instead of rewriting the whole summary.

## Plain-Language Concept Rule
Whenever the run introduces a new concept, acronym, or internal term:
- explain it immediately in ordinary language
- say what role it plays in the current run
- avoid stacking unexplained jargon

Good:
- "CPRB is the current repair variant the run is testing; in plain terms, it is a modified mechanism meant to keep source skill while improving the target behavior."

Bad:
- "CPRB improved target-slice specificity via same-family margin recovery."

If technical terms are necessary, translate them right away.

## Output Style
- Write for a human operator, not for another agent
- Prefer short paragraphs and bullets
- Distinguish **facts**, **inference**, and **uncertainty**
- If a claim is based on evidence from one report only, say that
- Do not overquote raw logs when a paraphrase is clearer

## Common Mistakes
### Mistake: turning the summary into a log replay
Fix: summarize the dominant thread of work and only expand by request.

### Mistake: confusing one reader/runner handoff with the whole run window
Fix: group evidence around the continuous session, not one hop.

### Mistake: giving a completion percentage without criteria
Fix: always show the component breakdown behind the completion judgment.

### Mistake: overstating weak evidence
Fix: explicitly mark uncertainty and say when evidence is insufficient.

### Mistake: leaving new terms unexplained
Fix: translate each new concept into plain language the first time it appears.

## Quick Reference
| Need | Action |
|---|---|
| User wants one-screen understanding | Give the First Response Contract only |
| User asks "why that conclusion?" | Expand **evidence** |
| User asks "what is this term?" | Expand **concepts** |
| User asks "should I keep going?" | Expand **completion** + **risks** |
| Evidence is weak | Say so directly and lower confidence |
