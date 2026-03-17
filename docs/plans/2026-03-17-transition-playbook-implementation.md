# Transition Playbook Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a supervised Transition Playbook workflow in Chainlit that validates a person move with ProConnect, generates a transparent Deep Research plan, runs research with live progress, validates opportunities with Credentials, and returns a compact action brief instead of a full raw report.

**Architecture:** Keep Chainlit as the workflow shell, but add a new transition-specific orchestration layer rather than overloading the existing generic chat paths. Reuse the current Deep Research client and BD orchestration, but insert a ProConnect preflight before research and a ProConnect actioning pass after credentials validation. Keep full research and dossier detail behind secondary actions instead of rendering them inline by default.

**Tech Stack:** Chainlit, React CustomElement UI, Azure AI Foundry Deep Research, Semantic Kernel, existing ContextFree/Credentials integration, ProConnect runtime client reused from current script logic.

---

### Task 1: Define Transition Playbook Contracts

**Files:**
- Create: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/models/transition_schemas.py`
- Modify: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/models/__init__.py`
- Test: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_schemas.py`

**Step 1: Write the failing tests**

Add tests for:
- a `TransitionRequest` model with `person_name`, `from_company`, `to_company`, `new_role`, `synthetic_scenario`, optional overrides
- a `TransitionPreflight` model with person/account resolution state, quick relationship indicators, suggested research prompt, inferred industry
- a `TransitionBrief` model with compact sections: transition summary, top opportunities, proof/warm paths, recommended actions, plus hidden artifacts metadata

**Step 2: Run test to verify it fails**

Run: `pytest '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_schemas.py' -q`

Expected: FAIL because schema module does not exist yet.

**Step 3: Write minimal implementation**

Create typed models that explicitly separate:
- input state
- preflight/validation state
- final brief state
- “hidden artifacts” references for full research report and full ProConnect dossier

Keep models narrow. Do not reuse `MDReport` directly for the top-level workflow object.

**Step 4: Run test to verify it passes**

Run: `pytest '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_schemas.py' -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add '/Users/salmaanrauf/Documents/BD Tool/Deep Research/models/transition_schemas.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/models/__init__.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_schemas.py'
git commit -m "feat: add transition playbook schemas"
```

### Task 2: Extract a Runtime ProConnect Transition Service

**Files:**
- Create: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/proconnect_transition_service.py`
- Modify: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/scripts/proconnect_stakeholder_payload.py`
- Modify: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/scripts/proconnect_lookup_logic.py`
- Test: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_proconnect_transition_service.py`

**Step 1: Write the failing tests**

Add tests proving the new service can:
- build a preflight payload from existing ProConnect resolution/builders
- return compact relationship indicators without needing CLI wrappers
- expose a deeper “actioning context” for post-research warm lead recommendations

**Step 2: Run test to verify it fails**

Run: `pytest '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_proconnect_transition_service.py' -q`

Expected: FAIL because the runtime service does not exist.

**Step 3: Write minimal implementation**

Refactor shared logic instead of duplicating script code in Chainlit:
- reuse `ProConnectClient`
- reuse account/person resolution helpers
- reuse stakeholder payload builders where sensible
- return Python objects directly, not CLI artifact wrappers

Keep the existing scripts working. Do not break local ProConnect testing.

**Step 4: Run targeted tests**

Run: `pytest '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_proconnect_transition_service.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/scripts/test_proconnect_stakeholder_payload.py' -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add '/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/proconnect_transition_service.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/scripts/proconnect_stakeholder_payload.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/scripts/proconnect_lookup_logic.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_proconnect_transition_service.py'
git commit -m "feat: add runtime proconnect transition service"
```

### Task 3: Add Transition Prompt Composition

**Files:**
- Create: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/transition_prompt_builder.py`
- Modify: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/prompt_loader.py`
- Test: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_prompt_builder.py`

**Step 1: Write the failing tests**

Add tests for:
- industry selection precedence: explicit override -> destination company industry -> source company industry -> `general`
- transition overlay appended to the industry prompt
- synthetic scenarios explicitly labeled as hypothetical in the user prompt
- generated prompt includes top opportunity hypotheses from ProConnect preflight

**Step 2: Run test to verify it fails**

Run: `pytest '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_prompt_builder.py' -q`

Expected: FAIL because the builder does not exist.

**Step 3: Write minimal implementation**

Build the final prompt from three layers:
- industry prompt from `PromptLoader`
- transition-specific overlay instructions
- generated user prompt body from validated transition context

Do not change existing generic prompt generation used by the current research form.

**Step 4: Run tests**

Run: `pytest '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_prompt_builder.py' -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add '/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/transition_prompt_builder.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/prompt_loader.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_prompt_builder.py'
git commit -m "feat: add transition prompt composition"
```

### Task 4: Build Transition Workflow Orchestrator

**Files:**
- Create: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/transition_playbook_orchestrator.py`
- Modify: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/bd_orchestrator.py`
- Test: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_playbook_orchestrator.py`

**Step 1: Write the failing tests**

Add tests covering:
- preflight-only flow returns a `TransitionPreflight`
- full run flow executes in sequence:
  1. ProConnect preflight
  2. Deep Research
  3. BDOrchestrator / Credentials / Final Analyst
  4. ProConnect actioning pass
- progress callback emits ordered stage events

**Step 2: Run test to verify it fails**

Run: `pytest '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_playbook_orchestrator.py' -q`

Expected: FAIL because the orchestrator does not exist.

**Step 3: Write minimal implementation**

The new orchestrator should be the one owner of the transition workflow. It should:
- expose `build_preflight(...)`
- expose `run_transition_playbook(...)`
- keep Deep Research polling intact by delegating to existing `run_deep_research(...)`
- keep Credentials inside `BDOrchestrator`, not duplicate that work
- add a final ProConnect recommendation pass after BD synthesis

Keep this separate from the generic `enhanced_user_request_handler`.

**Step 4: Run tests**

Run: `pytest '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_playbook_orchestrator.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_bd_orchestrator.py' -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add '/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/transition_playbook_orchestrator.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/bd_orchestrator.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_playbook_orchestrator.py'
git commit -m "feat: add transition playbook orchestrator"
```

### Task 5: Replace the Current Deep Research Input Form for This Flow

**Files:**
- Create: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/public/elements/TransitionForm.jsx`
- Modify: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/chainlit_app/main.py`
- Test: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_form_mapping.py`

**Step 1: Write the failing tests**

Add tests for Python-side form mapping only:
- required fields map into `TransitionRequest`
- advanced options are optional
- synthetic scenario flag persists in session

**Step 2: Run test to verify it fails**

Run: `pytest '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_form_mapping.py' -q`

Expected: FAIL because transition form mapping helpers do not exist.

**Step 3: Write minimal implementation**

Create a new CustomElement form with:
- required fields: person, from company, to company, new role
- one compact synthetic toggle
- advanced options expander

Do not delete `ResearchForm.jsx`; keep it for the existing generic deep research path until the new flow is stable.

**Step 4: Run tests**

Run: `pytest '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_form_mapping.py' -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add '/Users/salmaanrauf/Documents/BD Tool/Deep Research/public/elements/TransitionForm.jsx' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/chainlit_app/main.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_form_mapping.py'
git commit -m "feat: add transition intake form"
```

### Task 6: Add Transition Validation Review Screen and Actions

**Files:**
- Modify: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/chainlit_app/main.py`
- Create: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/transition_presenter.py`
- Test: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_presenter.py`

**Step 1: Write the failing tests**

Add tests for presenter output:
- preflight review screen contains compact transition summary
- generated prompt is hidden behind a “view prompt” action, not dumped inline
- primary actions are `Run Research`, `Edit Prompt`, `Adjust Transition`

**Step 2: Run test to verify it fails**

Run: `pytest '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_presenter.py' -q`

Expected: FAIL because presenter does not exist.

**Step 3: Write minimal implementation**

Create presenter helpers that:
- render a compact preflight review message
- use Chainlit actions instead of giant markdown dumps
- keep the prompt secondary via a collapsed/details block or action-driven secondary message

Do not intermingle this rendering with the existing `present_enhanced_response` function more than necessary.

**Step 4: Run tests**

Run: `pytest '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_presenter.py' -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add '/Users/salmaanrauf/Documents/BD Tool/Deep Research/chainlit_app/main.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/transition_presenter.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_presenter.py'
git commit -m "feat: add transition validation review screen"
```

### Task 7: Add Continuous Progress Surface Across ProConnect, Deep Research, and Credentials

**Files:**
- Modify: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/chainlit_app/main.py`
- Modify: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/transition_playbook_orchestrator.py`
- Modify: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/bd_orchestrator.py`
- Test: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_progress_events.py`

**Step 1: Write the failing tests**

Add tests ensuring:
- progress events are stage-based and factual
- Deep Research retains its existing polling/activity feed during the `Running deep research` stage
- Credentials emits stage updates with real counts rather than silent waits
- ProConnect emits factual stage updates without pretending to show hidden chain-of-thought

**Step 2: Run test to verify it fails**

Run: `pytest '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_progress_events.py' -q`

Expected: FAIL because the transition progress contract does not exist.

**Step 3: Write minimal implementation**

Create a single updated progress card that can show:
- current stage
- status line
- recent activity lines
- count highlights

Retain the current Deep Research polling callback implementation and slot it into the transition card during the research stage.

**Step 4: Run tests**

Run: `pytest '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_progress_events.py' -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add '/Users/salmaanrauf/Documents/BD Tool/Deep Research/chainlit_app/main.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/transition_playbook_orchestrator.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/bd_orchestrator.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_progress_events.py'
git commit -m "feat: add transition workflow progress surface"
```

### Task 8: Build a Compact Transition Brief Output

**Files:**
- Create: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/transition_brief_formatter.py`
- Modify: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/bd_report_formatter.py`
- Modify: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/chainlit_app/main.py`
- Test: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_brief_formatter.py`

**Step 1: Write the failing tests**

Add tests proving the default visible output:
- does not inline the full Deep Research report
- shows only transition summary, top opportunities, proof/warm paths, and next actions
- exposes `View Full Research Report` and `View ProConnect Dossier` as secondary actions/artifacts

**Step 2: Run test to verify it fails**

Run: `pytest '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_brief_formatter.py' -q`

Expected: FAIL because the new formatter does not exist.

**Step 3: Write minimal implementation**

Add a transition-specific formatter instead of stretching `response_formatter` or `bd_report_formatter` too far. Keep the existing BD formatter available for the old deep-research append-as-section flow until the transition workflow is stable.

**Step 4: Run tests**

Run: `pytest '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_brief_formatter.py' -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add '/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/transition_brief_formatter.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/bd_report_formatter.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/chainlit_app/main.py' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_brief_formatter.py'
git commit -m "feat: add compact transition brief output"
```

### Task 9: Integration, Verification, and Docs

**Files:**
- Modify: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/README.md`
- Modify: `/Users/salmaanrauf/Documents/BD Tool/Deep Research/Documentation/ENHANCED_SYSTEM_DOCUMENTATION.md`
- Modify: `/Users/salmaanrauf/Documents/BD Tool/AGENT_HANDOFF.md`

**Step 1: Run focused test suite**

Run:

```bash
pytest \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_schemas.py' \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_proconnect_transition_service.py' \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_prompt_builder.py' \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_playbook_orchestrator.py' \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_form_mapping.py' \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_presenter.py' \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_progress_events.py' \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_transition_brief_formatter.py' -q
```

Expected: PASS.

**Step 2: Run regression tests around existing critical flows**

Run:

```bash
pytest \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_bd_orchestrator.py' \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_credentials_agent.py' \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests/test_final_analyst_fallback_summary.py' \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/scripts/test_proconnect_stakeholder_payload.py' -q
```

Expected: PASS.

**Step 3: Run syntax and diff hygiene checks**

Run:

```bash
python3 -m py_compile \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/chainlit_app/main.py' \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/transition_playbook_orchestrator.py' \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/transition_brief_formatter.py' \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/transition_presenter.py' \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/transition_prompt_builder.py' \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/proconnect_transition_service.py' \
  '/Users/salmaanrauf/Documents/BD Tool/Deep Research/models/transition_schemas.py'

git diff --check
```

Expected: clean output.

**Step 4: Update docs**

Document:
- new Transition Playbook flow
- inferred industry prompt behavior
- preflight review before research
- full report hidden behind secondary actions
- progress semantics: factual activity, not hidden reasoning

**Step 5: Commit**

```bash
git add '/Users/salmaanrauf/Documents/BD Tool/Deep Research/README.md' '/Users/salmaanrauf/Documents/BD Tool/Deep Research/Documentation/ENHANCED_SYSTEM_DOCUMENTATION.md' '/Users/salmaanrauf/Documents/BD Tool/AGENT_HANDOFF.md'
git commit -m "docs: document transition playbook workflow"
```

---

## Implementation Notes

- Keep the generic enhanced chat flow working. The transition workflow should be additive, not a risky replacement.
- Keep Deep Research polling. It is a differentiator. Just present it as live research activity rather than hidden “thinking.”
- Do not let the transition workflow inline the full Deep Research report by default.
- Do not couple Chainlit UI directly to script-only ProConnect helpers; move runtime-safe logic into `services/`.
- Prefer adding a transition-specific formatter/presenter over bloating existing generic formatters.
- The first demo should optimize for clarity and trust, not autonomy.

## Suggested Commit Order

1. `feat: add transition playbook schemas`
2. `feat: add runtime proconnect transition service`
3. `feat: add transition prompt composition`
4. `feat: add transition playbook orchestrator`
5. `feat: add transition intake form`
6. `feat: add transition validation review screen`
7. `feat: add transition workflow progress surface`
8. `feat: add compact transition brief output`
9. `docs: document transition playbook workflow`
