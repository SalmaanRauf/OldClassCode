# Findings

Date: 2026-03-17

## Initial Implementation Review

- The Transition Playbook plan files are present under `/Users/salmaanrauf/Documents/BD Tool/docs/plans`.
- The repo contains the expected implementation anchors:
  - `/Users/salmaanrauf/Documents/BD Tool/Deep Research/chainlit_app/main.py`
  - `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/prompt_loader.py`
  - `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/bd_orchestrator.py`
  - `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/bd_report_formatter.py`
  - `/Users/salmaanrauf/Documents/BD Tool/Deep Research/public/elements/ResearchForm.jsx`
  - `/Users/salmaanrauf/Documents/BD Tool/Deep Research/models/__init__.py`
  - `/Users/salmaanrauf/Documents/BD Tool/Deep Research/scripts/test_proconnect_stakeholder_payload.py`
- `pytest` is available in the environment.
- The git worktree is dirty with unrelated untracked artifact directories and output files. These should be left alone.

## Implementation Notes

- The first batch can proceed without changing architecture assumptions.
- Execution logging should continue in both:
  - `/Users/salmaanrauf/Documents/BD Tool/docs/plans/2026-03-17-transition-playbook-execution-log.md`
  - `/Users/salmaanrauf/Documents/BD Tool/progress.md`

## Codebase Findings For Batch 1

- Existing BD schemas live in `/Users/salmaanrauf/Documents/BD Tool/Deep Research/models/bd_schemas.py`.
- `models/__init__.py` is currently minimal and safe to extend with transition schema exports.
- Existing tests in `/Users/salmaanrauf/Documents/BD Tool/Deep Research/tests` use:
  - direct `pytest`
  - `sys.path.insert(0, ...)` to import from the `Deep Research` package root
  - plain assertions rather than heavy fixtures unless needed
- `PromptLoader` is isolated in `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/prompt_loader.py`, which makes it straightforward to add transition prompt composition without disturbing generic prompt generation.
- The ProConnect stakeholder script already contains reusable helpers for:
  - account context
  - projects
  - opportunities
  - key buyers
  - from-company lite context
  - technologies
  - person enrichment from prospect detail
- There is already a script-level regression test file at `/Users/salmaanrauf/Documents/BD Tool/Deep Research/scripts/test_proconnect_stakeholder_payload.py`, which should be kept passing as Task 2 refactors shared logic into a runtime service.

## Batch 1 Outcome

- The new transition contracts were added without changing the existing BD schema hierarchy.
- The runtime ProConnect transition service was implemented as a thin wrapper over `run_stakeholder_case`, which avoids duplicating the ProConnect payload logic in Chainlit code.
- The new service can now:
  - load a transition case from the existing stakeholder flow
  - convert it into a compact `TransitionPreflight`
  - expose a deeper actioning context for later outreach recommendations
- Prompt composition now has a dedicated builder layer with:
  - explicit override -> inferred industry -> general precedence
  - a transition-specific system overlay
  - a structured user prompt that includes hypotheses and synthetic-scenario language
- `PromptLoader` now exposes `resolve_industry_key`, which is a useful normalization point for later orchestrator work.

## Batch 2 Prep Findings

- `chainlit_app/main.py` currently enters Deep Research mode through `show_research_form()` and `generate_research_prompt()`.
- The current `ResearchForm.jsx` path is separate enough that a new `TransitionForm.jsx` can be added without deleting or destabilizing the generic research flow.
- `tools/orchestrators.py::run_deep_research(...)` already exposes the right seam for the future transition orchestrator to delegate Deep Research runs and preserve polling.
- `services/bd_orchestrator.py` already owns the credentials and final analyst sequence, so the transition orchestrator should wrap it rather than replicate it.
- There is no existing app-side ProConnect token/config wiring outside the scripts.
- The ProConnect scripts already support the desired server-side auth pattern:
  - `PROCONNECT_BEARER_TOKEN` env var
  - `token.txt` fallback via `resolve_bearer_token(...)`
- That means the cleanest application-side approach is to reuse the script token resolver on the backend and never expose auth in the UI.

## Batch 2 Outcome

- The transition workflow now has a dedicated orchestrator in `/Users/salmaanrauf/Documents/BD Tool/Deep Research/services/transition_playbook_orchestrator.py`.
- That orchestrator:
  - owns preflight building
  - owns the full transition run sequence
  - can lazily bootstrap a backend ProConnect client using:
    - `PROCONNECT_BEARER_TOKEN` via the existing script resolver
    - `PROCONNECT_TOKEN_FILE` if explicitly configured
    - `token.txt` fallback behavior from the existing script utility
- This matches the user's preferred operational model: manual backend token refresh, hidden from MDs.
- The Deep Research path now supports `instructions_override`, which means the transition-specific system prompt overlay can actually flow into the existing polling-based Deep Research run.
- The new transition intake form and presenter are in place, but the flow is not yet fully connected as the default UI path. That will happen in later tasks.

## Batch 3 Findings

- The existing transition orchestrator needed richer stage metadata, not a new coordination layer.
- The cleanest way to keep the default output compact was to add a dedicated transition brief formatter instead of trying to repurpose the generic BD markdown renderer.
- Chainlit actions are sufficient for the hidden-artifact pattern:
  - `View Full Research Report`
  - `View ProConnect Dossier`
  - `View Source Evidence`
- Prompt editing needed a real backend path. The simplest correct implementation was a session-level prompt override passed into `run_transition_playbook(...)`.
- The user’s preferred ProConnect auth model maps directly to the current codebase because the shared script resolver already supports env token, explicit token file, and `token.txt` fallback.

## Run Guide Findings

- The existing standalone ProConnect harness guide in `Deep Research/scripts/RUN_GUIDE.md` was the right template for a live app runbook.
- The most important operational guidance for the other machine is:
  - use `PROCONNECT_TOKEN_FILE`
  - keep the token backend-only
  - validate the transition flow through the Chainlit mode, not through the standalone script harness
