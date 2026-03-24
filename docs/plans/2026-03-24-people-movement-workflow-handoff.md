# People Movement Workflow Handoff

## Purpose

This document is the handoff for the current `People Movement Brief` POC and the adjacent `Transition Playbook` / BD workflow. It captures:

- what the stakeholder actually wants
- why the product direction changed
- the agreed workflow and output shape
- what has already been built
- what was recently fixed
- what remains risky or unfinished
- where the next engineer should start

This should be treated as the current source of truth for the POC direction unless superseded by a newer dated handoff.

---

## Product Direction

### Why the use case changed

The original broader BD/opportunity-led output was judged too surface-level by MDs. The feedback was that LLM-led “findings” were too generic and easy to skim past. The product direction changed toward **people movement** because that is more concrete, more commercially legible, and a better fit for how MDs actually think about timing, leverage, and re-engagement.

The new concept is:

- keep Deep Research broad and valuable
- still find the full signal set
- but make the **cover artifact movement-led**
- use ProConnect to prove whether we know the people and where we have leverage
- use Credentials to prove likely consulting relevance

The broader Deep Research findings still matter, but they should be **secondary artifacts**, not the first thing shown.

### What the user wants

The target POC is a **named-move, structured-input workflow** that can power a demo such as:

> Jennifer Brady has moved from Capital One to Fannie Mae, with a new role as Chief Information Officer. Source all relevant information and find all people/buyer movement within the last 180 days.

But the user does **not** want a free-text-only UX. The intended experience is:

1. User fills a structured form once
2. System generates the research prompt from the form
3. User can review or edit the generated prompt
4. User clicks `Run Research`
5. System runs the full workflow
6. Final screen shows only the movement-led brief, not the whole raw report

### Explicit product decisions already made

- Primary mode is `People Movement Brief`
- Main artifact is a **structured app screen**, not a raw chat response and not a static PDF
- Input is **named-move structured intake**, not general company scan as the primary demo path
- Deep Research should still search the full signal set
- `Executive Movement` and `Buyer Movement` are separate first-class Financial Services signals
- `Buyer Movement` includes:
  - internal promotions / scope expansions
  - external job changes
  - adjacent strategic operators when the role clearly expands scope, budget, or influence
- Search window should be:
  - search up to 12 months
  - rank last 6 months highest
  - keep older moves only when still strategically active
- Cover output should stay close to the PDF style:
  - `Move Summary`
  - `Signal Summary`
  - `Who Has Moved — And Where We Have Leverage`
  - `Where to Act`
  - `Takeaway`
- Combined movement table should show both `EXEC` and `BUYER`
- Table should show up to 10 rows
- `Where to Act` should show only top 3 actions
- The full Deep Research report should be hidden behind secondary controls
- Credentials should remain **industry / opportunity / prior work oriented**, not “people movement for its own sake”
- ProConnect should enrich the named mover and discovered movers
- No subagents going forward unless the user explicitly asks again

---

## Intended End-to-End Workflow

### Intake

`People Movement Brief` should start from a structured form with:

- `Person`
- `From Company`
- `To Company`
- `New Role`
- `Lookback Days` default `180`
- `Synthetic Scenario` default `true`
- optional:
  - `Geography`
  - `Industry Override`
  - `Additional Context`

The system should generate a prompt from those fields. The user should not have to write the same content twice.

### Review Step

After form submit, the system should run **preflight**, not full research.

Preflight should validate and summarize:

- mover identity / person match state
- source account resolution
- destination account resolution
- warm path availability
- prior work at source / destination
- industry context
- prompt to be executed

The user should then see a **review surface** with active next-step controls:

- `Run Research`
- `Edit Prompt`
- `Adjust Movement`
- `View Generated Prompt`

### Research Run

When the user clicks `Run Research`, the system should run:

1. Named-move ProConnect preflight context
2. Broad Financial Services Deep Research
3. Signal evidence digestion
4. Movement digestion
5. Per-row ProConnect movement enrichment
6. Credentials lookup on top likely plays
7. Deterministic movement brief assembly

### Output

The main screen should show:

- `Move Summary`
- `Signal Summary`
- `Who Has Moved — And Where We Have Leverage`
- `Where to Act`
- `Takeaway`

The table should include leverage columns such as:

- `Signal`
- `Person`
- `Previous Role`
- `New Role`
- `Movement Type`
- `Known`
- `Worked With`
- `# Projects`
- `# Wins`
- `Relationship Owner`
- `Action`

Inline row details should reveal:

- evidence quote
- source link
- ProConnect detail
- credentials proof

Secondary artifacts should include:

- full Deep Research report
- additional signals
- movement evidence

---

## Current Architecture

There are currently **two overlapping systems** in the repo:

### 1. People Movement Brief path

This is the movement-led deterministic cover brief path.

High-level flow:

- Chainlit mode entry in [main.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/chainlit_app/main.py)
- intake mapping in [movement_form_mapper.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/movement_form_mapper.py)
- prompt composition in [movement_prompt_builder.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/movement_prompt_builder.py)
- orchestration in [movement_brief_orchestrator.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/movement_brief_orchestrator.py)
- movement extraction in [fs_movement_digestor.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/fs_movement_digestor.py)
- broad signal extraction in [fs_signal_evidence_digestor.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/fs_signal_evidence_digestor.py)
- movement enrichment in [proconnect_movement_service.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/proconnect_movement_service.py)
- credentials proof in [credentials_lookup_runner.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/credentials_lookup_runner.py), [movement_opportunity_deriver.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/movement_opportunity_deriver.py), and [movement_credentials_service.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/movement_credentials_service.py)
- final deterministic cover assembly in [movement_brief_assembler.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/movement_brief_assembler.py)
- rendering in [movement_presenter.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/movement_presenter.py) and [MovementBrief.jsx](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/public/elements/MovementBrief.jsx)

Important: this path does **not** use the Final Analyst to generate the visible cover.

### 2. Transition / old BD path

This remains the older synthesis-heavy path.

High-level flow:

- transition orchestration in [transition_playbook_orchestrator.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/transition_playbook_orchestrator.py)
- broader BD orchestration in [bd_orchestrator.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/bd_orchestrator.py)
- final synthesis in [final_analyst_agent.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/agents/final_analyst_agent.py)

This path still matters because:

- it contains the older proven credentials wiring
- it still supports `Transition Playbook`
- pieces of it were reused in the movement workflow

---

## What Has Been Built

### Movement-led POC features

Built and pushed:

- `People Movement Brief` Chainlit mode
- named-move movement intake
- generated prompt package
- broad Deep Research with movement emphasis
- separate `Executive Movement` and `Buyer Movement` handling
- movement digest stage
- movement table and deterministic brief presentation
- ProConnect preflight and movement enrichment
- credentials lookup reuse from the older path
- run-scoped workflow state for reviewed context
- artifact buttons for the hidden deeper outputs

### Reliability / workflow hardening already completed

Recent commits relevant to this work:

- `29d5913` `feat: add named-move movement orchestration`
- `8198433` `feat: wire named-move people movement brief`
- `3c27b4e` `fix: lazy-load final analyst during startup`
- `bdc0be8` `fix: lazy-load credentials agents during startup`
- `7c7784a` `fix: preserve custom element form submissions`
- `e988550` `feat: harden reviewed workflow execution`
- `4697f58` `feat: harden stable-id credentials and synthesis`
- `b2c1ecc` `fix: harden movement review workflow`

### Reliability fixes included in `b2c1ecc`

The latest fix addressed a real UX/control-flow bug:

- after preflight, the review screen could render with disabled or effectively dead action buttons
- this created the false impression that the run had stalled at `Account signals`
- in reality, Deep Research had often not started yet because `Run Research` was not actually clickable

The fix changed the review step from passive message actions to an explicit ask-response flow in:

- [main.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/chainlit_app/main.py)
- [review_flow.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/review_flow.py)

This was paired with:

- clearer progress-state wording in [movement_form_mapper.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/movement_form_mapper.py)
- clearer review copy in [movement_presenter.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/movement_presenter.py)
- better logging during movement and transition preflight/run
- package-safe ProConnect imports
- Semantic Kernel compatibility import cleanup

---

## What the User Explicitly Cares About

These preferences should be treated as hard guidance:

- do not assume the user is correct if the code says otherwise
- do the thinking, do not push work back to the user
- keep work local, not agent-heavy
- no subagents for future work unless explicitly requested
- be willing to challenge weak technical assumptions
- keep the product focused on the actual POC, not platform perfection
- avoid ad hoc changes; work from explicit plans
- do not regress the previously working credentials setup

Specific workflow preferences:

- credentials should support opportunity / prior work / industry proof
- movement should lead the cover, but broad research should still run underneath
- the full raw Deep Research report should not dominate the visible output
- the demo should feel intentional and trustworthy, not like a half-working AI toy

---

## Known Problems and Risks

### 1. The biggest recent problem was misleading workflow state

The UI used to show downstream stages as `pending` even when the system was only at preflight/review. That made it look like research had stalled. This should now be corrected, but it needs real end-to-end confirmation on the Windows machine where the user runs the app.

### 2. Local UI smoke testing is still environment-limited

On this Mac workspace, full Chainlit runtime UI testing is limited by missing app env vars. Code-level import smoke and targeted tests passed, but the final confirmation still depends on the user’s Windows runtime.

### 3. There are still unrelated dirty files in the worktree

At the time of this handoff, there are unrelated modified and untracked files not part of the pushed workflow fix. Do not assume the entire local worktree is clean. Only rely on committed history for the shipped state.

### 4. There may still be downstream runtime issues once `Run Research` is clicked

The latest fix addresses the review-step dead-end. If the next failure happens **after** `Run Research`, the likely areas are:

- Deep Research environment/config
- ProConnect auth/runtime
- credentials lookup/config
- movement digest edge cases on target-company aliasing

The logging is now much better than before, so the next failure should be easier to localize.

### 5. Final Analyst is still only part of the transition / BD path

If someone assumes the `People Movement Brief` visible cover is generated by `FinalAnalystAgent`, that assumption is wrong. The movement cover is deterministic and assembled outside the Final Analyst path.

---

## What Was Verified

Verified locally before push:

- `94 passed` across the targeted workflow/digest/orchestrator/credentials tests
- `python3` import smoke passed for:
  - movement services
  - transition services
  - final analyst module
  - kernel setup
  - `chainlit_app.main`
- `py_compile` passed on touched runtime modules
- `git diff --check` passed

Important constraint:

- a full browser/UI run was not completed locally because the required app env vars were missing in this environment

---

## Where the Next Engineer Should Start

### First priority

Confirm the latest fix on the actual Windows demo machine:

1. pull `main`
2. launch Chainlit
3. open `People Movement Brief`
4. submit the named-move form
5. confirm the review step shows active next-step controls
6. click `Run Research`
7. verify terminal logging now shows the real run kickoff and subsequent progress

### What to look for in logs

Expected post-review logs should include:

- movement review selection
- movement research requested
- Deep Research dispatch/start
- normalized progress events

If the UI still freezes, capture:

- what the review screen shows
- whether buttons are clickable
- the exact terminal lines after clicking `Run Research`

### If the next issue occurs after research starts

Investigate in this order:

1. [movement_brief_orchestrator.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/movement_brief_orchestrator.py)
2. [deep_research_client.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/deep_research_client.py)
3. [fs_signal_evidence_digestor.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/fs_signal_evidence_digestor.py)
4. [fs_movement_digestor.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/fs_movement_digestor.py)
5. [proconnect_movement_service.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/proconnect_movement_service.py)
6. [credentials_lookup_runner.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/credentials_lookup_runner.py)

### If the issue is still review-step related

Investigate:

- [main.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/chainlit_app/main.py)
- [review_flow.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/review_flow.py)
- [movement_presenter.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/movement_presenter.py)

---

## Recommended Next Work Items

Only after the live Windows retest confirms the review fix:

1. Run a full happy-path movement demo with a realistic named move
2. Validate that the progress card reflects actual state transitions
3. Confirm the full movement brief renders with row details and hidden artifacts
4. If research starts but hangs later, capture exact stage and fix the real downstream blocker
5. Add one true end-to-end UI regression test around:
   - form submit
   - review step
   - `Run Research`
   - visible progress transition

If the user wants quality uplift after stability:

1. tighten movement table ranking
2. improve `Where to Act` quality using stronger credential weighting
3. refine empty/degraded-state messaging

---

## Repo Hotspots

Most relevant files for this POC:

- [main.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/chainlit_app/main.py)
- [MovementScanForm.jsx](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/public/elements/MovementScanForm.jsx)
- [MovementBrief.jsx](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/public/elements/MovementBrief.jsx)
- [movement_form_mapper.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/movement_form_mapper.py)
- [movement_presenter.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/movement_presenter.py)
- [movement_prompt_builder.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/movement_prompt_builder.py)
- [movement_brief_orchestrator.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/movement_brief_orchestrator.py)
- [review_flow.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/review_flow.py)
- [fs_signal_evidence_digestor.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/fs_signal_evidence_digestor.py)
- [fs_movement_digestor.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/fs_movement_digestor.py)
- [proconnect_transition_service.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/proconnect_transition_service.py)
- [proconnect_movement_service.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/proconnect_movement_service.py)
- [credentials_lookup_runner.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/credentials_lookup_runner.py)
- [movement_opportunity_deriver.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/movement_opportunity_deriver.py)
- [bd_orchestrator.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/services/bd_orchestrator.py)
- [final_analyst_agent.py](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/agents/final_analyst_agent.py)

---

## Bottom Line

The POC is supposed to be a **movement-led, named-move brief** with real Deep Research, real ProConnect, and real credentials behind it. The latest shipped fix addressed a broken review control-flow bug that made the app look like it was stalling before research had even begun. The immediate next step is not more speculative redesign. It is a real Windows-machine retest of the post-preflight review and the `Run Research` transition.
