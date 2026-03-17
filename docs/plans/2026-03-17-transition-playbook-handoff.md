# Transition Playbook Handoff

Date: 2026-03-17
Workspace: `/Users/salmaanrauf/Documents/BD Tool`
Related plan: [2026-03-17-transition-playbook-implementation.md](/Users/salmaanrauf/Documents/BD%20Tool/docs/plans/2026-03-17-transition-playbook-implementation.md)

## Purpose

Preserve the key product, UX, and architecture decisions from the design session so a fresh implementation session can start without re-deriving intent.

## Core Product Goal

Build a supervised `Transition Playbook` workflow for executive-move scenarios.

The workflow should:
- validate a move with ProConnect
- generate a transparent Deep Research plan
- run Deep Research with live progress
- validate top opportunities with the Credentials Agent
- use ProConnect again for warm paths, relationship context, and outreach guidance
- return a compact action brief instead of dumping the full research report inline

## Demo Scenario

Primary demo scenario discussed:

`Jennifer Brady has moved from Capital One to Fannie Mae, and is joining on as a Chief Information Officer. Discover new opportunities and warm leads.`

Important:
- this move is synthetic for demo purposes
- the product must make that explicit in the UI
- research prompts and system instructions must treat this as a planning assumption, not as a verified public fact

## User Priorities

The user explicitly prefers:
- clarity and trust over maximum automation
- a lightweight experience for MDs
- transparency into what the system is doing
- visible progress during long-running work
- durable notes during implementation covering:
  - what was changed
  - how it was changed
  - decisions made
  - blockers
  - user preferences

The user does not want:
- a laborious intake process
- the default output to be a massive wall of Deep Research text
- fake "agent thinking" that looks like hidden reasoning

## Agreed UX Shape

### Input

Use a structured form plus generated prompt preview.

Default required fields:
- `Person`
- `From Company`
- `To Company`
- `New Role`

Default optional toggle:
- `Synthetic scenario`

Advanced options should be hidden by default and may include:
- department hint
- geography
- additional context
- industry override if needed

### Pre-Run Flow

After form submit:
- run a fast ProConnect preflight automatically
- do not show the full dossier yet
- show a compact `Transition Validation` surface

That validation surface should show:
- person match confirmed
- source account resolved
- destination account resolved
- quick relationship indicators
- quick prior work indicators
- compact prompt preview

Primary CTA:
- `Run Research`

Secondary CTAs:
- `Edit Prompt`
- `Adjust Transition`

The full prompt should be visible, but secondary:
- use a collapsed `View generated prompt` panel by default

### Output

Default visible output should be an executive action brief with four sections:
- `Transition Summary`
- `Top Opportunities`
- `Proof + Warm Paths`
- `Recommended Actions`

The full Deep Research report should not be rendered inline by default.

Secondary drill-down controls should expose:
- full research report
- full ProConnect dossier
- detailed evidence / sources

## Agreed Workflow

1. `Transition Setup`
2. `Transition Validation`
3. `Research Plan Review`
4. `Running Deep Research`
5. `Credentials Validation`
6. `Warm Lead / Outreach Mapping`
7. `Transition Brief`

## Progress Model

Use factual stage-based progress, not faux hidden chain-of-thought.

Stages agreed:
- `Resolving transition`
- `Building relationship context`
- `Generating research plan`
- `Running deep research`
- `Validating credentials`
- `Mapping warm leads`
- `Assembling brief`

Progress lines should include real findings when possible, for example:
- person matched
- source/destination accounts resolved
- warm path count
- top opportunity hypothesis count
- credential matches found

Deep Research polling must be preserved.

Meaning:
- keep the current live polling/activity behavior for Deep Research
- frame it as `Research activity` or `Live research progress`
- do not present it as private model reasoning

ProConnect and Credentials do not need polling if we own those calls.
They should emit stage-based progress updates with real counts and statuses.

## Prompt Strategy

Keep the current industry system prompts.

Do not force the user to choose industry as a primary input.
Instead, infer it by default with this precedence:

1. explicit user override
2. destination company industry from ProConnect
3. source company industry
4. `general`

Prompt composition should be layered:
- base industry prompt
- transition-specific overlay
- generated user prompt from the validated transition context

The transition overlay should emphasize:
- executive-move scenario
- role-relevant opportunities
- timing and "why now"
- consulting fit
- synthetic/hypothetical treatment when applicable

## Architecture Snapshot

There are effectively two existing flows:

1. Standard Chainlit / enhanced task flow
- `chainlit_app/main.py`
- `tools/orchestrators.py`
- `services/enhanced_router.py`
- `tools/task_executor.py`

2. Deep Research + BD enrichment flow
- `chainlit_app/main.py`
- `services/deep_research_client.py`
- `services/bd_orchestrator.py`
- `agents/credentials_agent.py`
- `agents/final_analyst_agent.py`

Important current-state observation:
- the Credentials Agent already exists and is already used in the Deep Research/BD path
- the likely work is to integrate this into a transition-specific workflow, not to invent credentials support from scratch

## Implementation Direction

Recommended implementation style:
- keep Chainlit for the demo
- add a transition-specific workflow instead of overloading the generic flow
- keep current generic research flow available until the new path is stable
- reuse existing Deep Research polling
- reuse existing ProConnect logic by extracting a runtime service from the current script-oriented implementation

## Files Expected To Matter

High-signal files for implementation:
- `/Users/salmaanrauf/Documents/BD Tool/Deep Research/chainlit_app/main.py`
- `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/deep_research_client.py`
- `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/bd_orchestrator.py`
- `/Users/salmaanrauf/Documents/BD Tool/Deep Research/agents/credentials_agent.py`
- `/Users/salmaanrauf/Documents/BD Tool/Deep Research/agents/final_analyst_agent.py`
- `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/prompt_loader.py`
- `/Users/salmaanrauf/Documents/BD Tool/Deep Research/public/elements/ResearchForm.jsx`
- `/Users/salmaanrauf/Documents/BD Tool/Deep Research/scripts/proconnect_stakeholder_payload.py`
- `/Users/salmaanrauf/Documents/BD Tool/Deep Research/scripts/proconnect_client.py`
- `/Users/salmaanrauf/Documents/BD Tool/Deep Research/models/bd_schemas.py`

Planned new files are documented in the implementation plan.

## Guardrails

- Do not dump the full Deep Research report into the main output by default.
- Do not make MDs fill a long analyst-style form.
- Do not overclaim that the move is factual when marked synthetic.
- Do not remove existing Deep Research polling.
- Do not break the current generic research path while building the transition flow.
- Keep implementation notes updated as work proceeds.

## Notes On Context Preservation

This file captures the design decisions that matter most for a fresh implementation session.
Use it together with:
- [2026-03-17-transition-playbook-implementation.md](/Users/salmaanrauf/Documents/BD%20Tool/docs/plans/2026-03-17-transition-playbook-implementation.md)
- [2026-03-17-transition-playbook-execution-log.md](/Users/salmaanrauf/Documents/BD%20Tool/docs/plans/2026-03-17-transition-playbook-execution-log.md)
