# Company Intelligence Chat — Tool-Centric Architecture

This package is a clean, self-contained version of your Chainlit chat workflow for company intelligence. It uses Azure AI Agents with Bing Grounding for discovery (GWBS) and Semantic Kernel (via ATLAS/Azure OpenAI) for analysis. Everything required to run the chat experience lives inside this folder.

## Quickstart

- Create a `.env` from `env.example` and fill in the Azure/ATLAS keys.
- Install: `pip install -r requirements.txt`
- Run: `python launch_chainlit.py`
- Open: http://localhost:8000

### Required Environment Variables (Standard Mode)
- **Discovery (Bing Grounding)**: `PROJECT_ENDPOINT`, `MODEL_DEPLOYMENT_NAME`, `AZURE_BING_CONNECTION_ID`
- **Analysis (Semantic Kernel/ATLAS)**: `OPENAI_API_KEY`, `BASE_URL`, `PROJECT_ID`, `API_VERSION`, `MODEL`
- **Feature flag**: `ENABLE_TOOL_ORCHESTRATOR` (on by default in `env.example`)

### Additional Configuration for Deep Research Mode (Optional)

Deep Research mode uses Azure AI Foundry's managed Deep Research tool with the `o3-deep-research` model for multi-hop, iterative research.

#### Prerequisites
1. **Azure Subscription** with access to Azure AI Foundry
2. **Model Access**: Request access to o3 model family at https://aka.ms/OAI/deepresearchaccess
3. **RBAC**: Ensure your account has "Azure AI User" role on the AI Foundry Project

#### Critical Regional Requirements ⚠️
**ALL** of the following resources **MUST** be in the **SAME** region (West US or Norway East):
- Azure AI Foundry Resource
- Azure AI Foundry Project
- `o3-deep-research` model deployment (version 2025-06-26)
- `gpt-4o` model deployment (used for intent clarification)

Failure to co-locate resources will result in `(unsupported_tool)` errors.

#### Setup Steps
1. **Create Azure AI Foundry Resource** in West US or Norway East
2. **Create Azure AI Foundry Project** in the same region
3. **Create Grounding with Bing Search resource**:
   ```bash
   # Register Microsoft.Bing provider if needed
   az provider register --namespace 'Microsoft.Bing'
   ```
4. **Connect Bing to AI Project**:
   - Navigate to Azure AI Foundry Project → Connected resources
   - Add connection to your Bing Grounding resource
   - Copy the **Connection ID** (not the display name)
5. **Deploy Models** in the **same region**:
   - Deploy `o3-deep-research` (version 2025-06-26)
   - Deploy `gpt-4o`
6. **Configure Environment Variables**:
   ```bash
   ENABLE_DEEP_RESEARCH=true
   DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME=<your-o3-deployment-name>
   BING_CONNECTION_NAME=<bing-connection-id-from-step-4>
   ```

### Additional Configuration for Transition Playbook Mode (Optional)

Transition Playbook mode layers ProConnect context on top of Deep Research so account leaders can validate a move, review a generated research plan, and then run a compact transition brief workflow.

Required backend auth options for ProConnect:
- `PROCONNECT_BEARER_TOKEN` or
- `PROCONNECT_TOKEN_FILE`

For the current demo flow, a manually refreshed backend `token.txt` file is also supported through the existing ProConnect script resolver. The UI never exposes this token.

Runbook:
- See [Documentation/TRANSITION_PLAYBOOK_RUN_GUIDE.md](/Users/salmaanrauf/Documents/BD%20Tool/Deep%20Research/Documentation/TRANSITION_PLAYBOOK_RUN_GUIDE.md) for the Windows/VPN validation steps.

#### Switching Between Modes
- Users can toggle between Standard, Deep Research, and Transition Playbook modes via the Chainlit UI
- Deep Research mode automatically falls back to Standard mode on errors
- Transition Playbook mode runs a ProConnect preflight first, shows a generated research prompt behind a secondary action, and only runs Deep Research after the user clicks `Run Research`
- Check logs for detailed error messages if Deep Research fails

## What It Does

- New analysis: Runs GWBS across SEC, News, Procurement, Earnings, Industry Context; passes results into Semantic Kernel to synthesize events and insights; presents a concise, grounded briefing.
- Follow-ups: Answers from context when possible; otherwise runs targeted GWBS searches; if the ask implies synthesis (why/how/impact/angle/priority/timeline), routes the new information through Semantic Kernel.
- Competitor ask: Runs a GWBS competitor analysis (fast) and adds citations; only invokes Semantic Kernel if the user asks for implications/angle.
- Comparison (A vs B): Legacy path comparing two companies remains available.

## What’s New In This Iteration

- Async-safe GWBS: All Bing Grounding calls are offloaded to background threads to keep the Chainlit event loop responsive.
- Per-scope timeouts: Each GWBS scope has a 45s timeout with graceful degradation if one scope fails.
- Streaming progress: New analysis streams per-scope progress (SEC, News, Procurement, Earnings, Industry) as they complete.
- Centralized classifier: One source of truth for request classification and scope mapping in `services/classifier.py`, used by router, orchestrator, and legacy follow-ups.
- General request handling: Multi-intent inputs (e.g., briefing + “risk/competitors/strategy”) are addressed automatically after the briefing using the unified follow-up pipeline.
- Stable public API: Added `search_competitors` on the Bing agent (no private method coupling).
- Transition Playbook workflow: Added a structured executive-move workflow with ProConnect preflight, live progress updates, editable prompt preview, compact transition brief output, and secondary artifact actions for full research and ProConnect dossier detail.

## High-Level Workflow

1) User sends a message in Chainlit.
- Router classifies intent: new analysis, follow-up, compare, or clarification.
- The orchestrator runs the necessary tools and returns a typed result.
- Chainlit presents concise summaries with annotation-derived citations.

2) New analysis (briefing):
- GWBS per scope → typed sections.
- Convert to typed `AnalysisItem[]`.
- Semantic Kernel performs synthesis → `AnalysisEvent[]`.
- Assemble a `Briefing` (summary + events + per-section summaries) and present.

3) Follow-up:
- Try to answer from context blob (summary + events) lexically.
- If insufficient, run targeted GWBS by label (risk/financial/strategic/regulatory/timeline/general).
- If the ask implies synthesis, pass results through Semantic Kernel and respond with synthesized answer.

4) Competitor ask (optional in the same turn):
- A separate GWBS “competitors” task identifies top competitors and what they’re doing.
- Present results with citations; run analyst only if the ask involves implications/strategy.

5) Transition Playbook:
- User selects `Transition Playbook` mode and completes the structured form (`person`, `from company`, `to company`, `new role`, optional advanced fields).
- App runs a ProConnect preflight automatically and posts factual progress updates.
- User reviews the compact transition validation screen and can inspect or edit the generated Deep Research prompt.
- After `Run Research`, the app preserves Deep Research polling, runs Credentials / final analyst synthesis, then renders a compact transition brief.
- Full Deep Research output and a richer ProConnect dossier are available behind secondary actions.

## ASCII Diagram

```
User ──▶ Chainlit (chainlit_app/main.py)
          │
          │ route: NEW_ANALYSIS / FOLLOW_UP / COMPARE / CLARIFY
          ▼
   Orchestrators (tools/orchestrators.py)
      ├─ full_company_analysis(CompanyRef)
      │     │
      │     ├─ GWBS Tools (tools/gwbs_tools.py)
      │     │    gwbs_full → {sec, news, procurement, earnings, industry}
      │     │
      │     └─ Analyst Tool (tools/analyst_tools.py)
      │          Semantic Kernel → AnalysisEvent[]
      │
      ├─ follow_up_research(CompanyRef, question)
      │     ctx lookup → targeted GWBS → optional SK
      │
      └─ competitor_analysis(CompanyRef)
            GWBS direct (optional SK if asked)
```

## Citation Policy

- Summaries strip inline URLs.
- Citations only come from Bing tool annotations; never from inline model output.
- Citations are merged and capped; presented as Markdown bullets.

## Caching

- `services/cache.py` provides a simple TTL cache for GWBS calls to reduce cost/latency.
- Keying by `(company, scope)`, default TTL = 30 minutes.

## File & Module Guide

- chainlit_app/
  - `main.py`: Chainlit UI handlers (chat start, on_message). Orchestrates standard analysis, deep research, and transition playbook workflows. Uses the tool orchestrator when `ENABLE_TOOL_ORCHESTRATOR` is true.
  - `.chainlit/config.toml`: UI config.
  - `chainlit.md`: In-app readme.

- agents/
  - `bing_data_extraction_agent.py`: Bing Grounded Search agent using Azure AI Agents; writes summaries and includes citation annotations only (with one corrective pass when missing). Public helpers: `search_sec_filings`, `search_news`, `search_procurement`, `search_earnings`, `search_industry_context`; `get_full_intelligence` bundle.
  - `analyst_agent.py`: Semantic Kernel-backed analysis pipeline (triage, financial/procurement/earnings analyzers, insight generation). Loads prompt templates from `sk_functions/` via `config/kernel_setup.py` (ATLAS/Azure OpenAI).

- tools/
  - `gwbs_tools.py`: Typed wrappers over Bing agent; convert annotation markdown to `Citation[]`; includes a `competitors` task prompt.
  - `analyst_tools.py`: Typed wrapper for SK analysis (`analyst_synthesis`).
  - `orchestrators.py`: High-level tool composition (async/concurrent with streaming + timeouts):
    - `full_company_analysis(CompanyRef) -> Briefing`
    - `follow_up_research(CompanyRef, question) -> (answer, citations)`
    - `competitor_analysis(CompanyRef) -> GWBSSection`

- services/
  - `conversation_manager.py`: `ConversationContext`, `AnalysisBlob`, `QueryRouter` + cleanup loop.
  - `session_manager.py`: Thread-safe in-memory session store with idle cleanup.
  - `follow_up_handler.py`: Legacy follow-up handler, now using the centralized classifier (kept for compatibility when orchestrator is disabled).
  - `classifier.py`: Centralized classification (labels, scope mapping, and synthesis decision) used across router and orchestrators.
  - `cache.py`: Simple TTL cache with a stable `cache_key` builder.
  - `transition_playbook_orchestrator.py`: Owns the transition workflow end-to-end (ProConnect preflight -> Deep Research -> Credentials/MD report -> ProConnect actioning).
  - `proconnect_transition_service.py`: Runtime wrapper around the existing ProConnect stakeholder payload builder.
  - `transition_prompt_builder.py`: Builds the transition-specific Deep Research system prompt overlay plus generated user prompt.
  - `transition_brief_formatter.py`: Produces the compact transition brief and secondary artifact payloads.
  - `transition_presenter.py`: Builds compact validation, progress, and brief surfaces for Chainlit.

- models/
  - `schemas.py`: Pydantic contracts for tools/orchestrators (`CompanyRef`, `Citation`, `GWBSSection`, `FullGWBS`, `AnalysisItem`, `AnalysisEvent`, `Briefing`).
  - `transition_schemas.py`: Dedicated Transition Playbook input, preflight, and compact brief contracts.

- config/
  - `kernel_setup.py`: SK kernel initialization (ATLAS/Azure OpenAI): creates `Kernel`, adds service, configures JSON response format.
  - `config.py`: Env loader/validator for required keys.

- sk_functions/
  - `Triage_CategoryRouting_prompt.txt`: Classifies and routes raw text.
  - `FinancialEvent_Detection_prompt.txt`: Detects ≥ $10M impact events.
  - `OpportunityIdent_skprompt.txt`: Extracts procurement opportunities.
  - `EarningsCall_GuidanceAnalysis_prompt.txt`: Finds forward-looking guidance.
  - `StrategicInsight_Generation_prompt.txt`: Produces partner-ready insights with consulting angle.
  - `CompanyTakeaway_skprompt.txt`: Generates per-company takeaway rollups.

- Root helpers
  - `requirements.txt`: Minimal dependencies for the chat use case.
  - `env.example`: Required environment variables and feature flag.
  - `launch_chainlit.py`: Launches Chainlit with environment validation and `PYTHONPATH` set.

- public/elements/
  - `ResearchForm.jsx`: Existing generic Deep Research research-parameter form.
  - `TransitionForm.jsx`: Structured transition intake form for the executive-move workflow.

## How It Decides When To Use SK vs GWBS Direct

- GWBS direct is used for list/lookup questions — “who/what/when/where/which” — and competitor overviews.
- SK is invoked when synthesis is required — “why/how/impact/angle/priority/timeline” — or when insights must be mapped to consulting services and urgency.

## Error Handling & Observability

- Orchestrator steps stream per-scope collection progress; analysis and any extra requests are reported separately.
- Errors return user-friendly messages and log context to stdout (suitable for container logs). You can add metrics around the tool boundaries if needed.

## Configuration Checklist

- Verify `.env` has all Azure/ATLAS keys set.
- Ensure `ENABLE_TOOL_ORCHESTRATOR=true` to use the new tool flow (legacy path still available if off).
- Optional: tune TTL in `services/cache.py`.

## Extending The System

- Add a new discovery scope: implement a task in `gwbs_tools.py`, update `gwbs_full` if it’s a default scope, and extend the orchestrator.
- Add a new analysis function: add a prompt to `sk_functions/`, wire it in `AnalystAgent._load_functions`, and map it in `analyst_tools.py`.
- Add a new intent: extend router classification in `services/conversation_manager.py` or augment orchestrators.

---

This folder is intentionally focused on the Chainlit chat use case and excludes batch ETL components. It is ready to run and iterate on without the noise of the larger repository.
