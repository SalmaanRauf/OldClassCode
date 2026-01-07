# Company Intelligence System Architecture (Enhanced Chainlit Workflow)

## Overview
The enhanced Company Intelligence system is a modular, intent-aware workflow that orchestrates company briefings, competitor sweeps, and general research from a single Chainlit chat surface. The design emphasises plan-based execution, strict citation hygiene, and reuse of the legacy Account Context experience while enabling new research paths.

---

## System Architecture Diagram
┌────────────────────────────────────────────────────────────────────────────┐
│                        USER EXPERIENCE (Chainlit UI)                       │
│ ┌───────────────────────────────────────────────────────────────────────┐  │
│ │ chainlit_app/main.py                                                   │  │
│ │ - Session lifecycle & telemetry                                        │  │
│ │ - Profile cache warm-up                                                │  │
│ │ - Delegates requests to enhanced orchestrator                          │  │
│ └──────────────┬───────────────────────────┬──────────────────────────────┘  │
                 │                           │
                 │ progress events           │ cached conversation context
                 ▼                           ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                ORCHESTRATION & INTENT RESOLUTION LAYER                      │
│ ┌───────────────────────────────────────────────────────────────────────┐  │
│ │ tools/orchestrators.enhanced_user_request_handler                      │  │
│ │ - Normalises user input + context                                      │  │
│ │ - Invokes intent resolver and task executor                            │  │
│ └──────────────┬──────────────────────────────┬──────────────────────────┘  │
                 │                              │
                 │ IntentPlan                   │ tasks + progress hooks
                 ▼                              ▼
┌──────────────────────────────┐      ┌────────────────────────────────────┐
│ services/enhanced_router     │      │ tools/task_executor                │
│ services/intent_resolver     │      │ - Fan-out via asyncio gather       │
│ SK `intent_resolver` prompt  │      │ - Per-task timeouts & error fences │
└──────────────┬───────────────┘      └──────────────┬────────────────────┘
               │                                     │
               │                                     │
               ▼                                     ▼
        ┌──────────────────────────────┐   ┌──────────────────────────────┐
        │ COMPANY ANALYSIS LANE        │   │ GENERAL RESEARCH LANE        │
        │ tools/orchestrators          │   │ tools/general_research_...   │
        │ - full_company_analysis      │   │ - market/industry/regulator  │
        └──────────────┬──────────────┘   └──────────────┬──────────────┘
                       │                             │
                       ▼                             ▼
           ┌──────────────────────────┐   ┌──────────────────────────┐
           │ Bing GWBS scopes         │   │ Bing topical helpers      │
           │ agents/bing_data_...     │   │ agents/bing_data_...      │
           └──────────────┬───────────┘   └──────────────┬───────────┘
                          │                              │
                          ▼                              ▼
               ┌──────────────────────────┐    ┌──────────────────────────┐
               │ Analyst Agent (shared)   │    │ Analyst Agent (shared)   │
               │ agents/analyst_agent     │    │ (same insight pipeline)  │
               └──────────────┬───────────┘    └──────────────┬───────────┘
                              │                              │
                              └──────────┬───────────────────┘
                                         ▼
                            ┌───────────────────────────────┐
                            │ tools/response_formatter       │
                            │ - merges summaries, events     │
                            │ - rebuilds Account Context     │
                            │ - deduplicates citations       │
                            └──────────────┬────────────────┘
                                           ▼
                            ┌───────────────────────────────┐
                            │ chainlit_app/main.py presenter │
                            │ - Streams GWBS appendix        │
                            │ - Streams analyst insights     │
                            │ - Streams account context      │
                            │ - Emits consolidated sources   │
                            └───────────────────────────────┘

(Shared utilities: `services/company_profiles`, `services/cache.TTLCache`, `services/conversation_manager`, `tools/gwbs_tools`.)

---

## Component Breakdown
- **Chainlit UI (`chainlit_app/main.py`)**: Owns session state, hooks up progress reporting, loads company profiles, and publishes the final structured response.
- **Enhanced Orchestrator (`tools/orchestrators`)**: Central coordinator that calls the router, spins up task execution, and hands work to `response_formatter`.
- **Intent Resolution (`services/enhanced_router`, `services/intent_resolver`, `sk_functions/Intent_Resolver_prompt.txt`)**: Combines SK inference with rule-based fallback to produce an `IntentPlan` (intent type, tasks, entities, confidence, reasoning).
- **Task Execution (`tools/task_executor`)**: Creates async coroutines per task, enforces scope-specific timeouts, captures partial failures, and emits progress updates.
- **Research Agents (`agents/bing_data_extraction_agent`)**: Provides core GWBS scopes plus eight new topical helpers (market overview, industry analysis, regulatory updates, competitor sweeps, general topics, unrestricted company lookup, location-based finance, technology trends).
- **General Research Orchestrator (`tools/general_research_orchestrator`)**: Wraps Bing topical helpers for non-company intents, returning consistent payloads for the formatter.
- **Analyst Agent (`agents/analyst_agent` + SK prompts)**: Performs triage, extracts structured quantitative insights, enriches with company profile data, and generates consulting takeaways.
- **Response Formatter (`tools/response_formatter`)**: Normalises task outputs into a unified payload (summary, events, raw GWBS, account context, citations, runtime metadata).
- **Data services**: `services/company_profiles` (profile cache), `services/cache` (briefing + GWBS TTL caches), `services/conversation_manager` (conversation history & analysis reuse).

---

## Request Lifecycle (Detailed)
1. **User Message**: Chainlit receives input and calls `_handle_message`.
2. **Context Prep**: Session state, cached analyses, and company profile data are loaded or initialised.
3. **Intent Planning**: Enhanced router invokes the SK `intent_resolver` function; if confidence < 0.7, the rule router produces a deterministic plan.
4. **Task Fan-out**: `task_executor` spins up coroutines for each planned task (company briefing, competitor sweep, general research, follow-up reuse) and wires progress callbacks.
5. **Data Retrieval**:
   - Company tasks run GWBS scopes (SEC, news, procurement, earnings, industry context) via Bing.
   - General research tasks call the relevant Bing topical helper (market overview, regulatory updates, etc.).
   - Follow-ups consult cached briefings and optionally run targeted Bing refreshes for gaps.
6. **Analyst Synthesis**: GWBS summaries are triaged, quantitative details extracted, and insights generated with embedded company profile context.
7. **Formatting & Delivery**: `response_formatter` assembles results; Chainlit streams progress and publishes the structured payload (GWBS appendix -> analyst view -> account context -> citations).
8. **Caching**: Briefings and GWBS sections are cached for 30 minutes to accelerate follow-ups while avoiding stale data.

---

## Task Lanes
| Lane | Trigger | Key Steps | Output |
| --- | --- | --- | --- |
| Company briefing | Company mentioned in intent plan | GWBS scopes -> Analyst synthesis -> Account context rebuild | Briefing summary, events, GWBS sections, citations. |
| Competitor sweep | Mixed request referencing competitors | Bing competitor helper -> Analyst summary | Competitor insight block w/ citations. |
| General research | No company detected or explicit topical ask | General research orchestrator -> Bing topical helper | Research digest with scope labels + citations. |
| Follow-up reuse | Intent type `follow_up` | Cache lookup -> optional targeted Bing refresh -> summarise hits | Short-form answer referencing existing citations. |

---

## Data & Caching
- **Company profiles**: Reside in `agentic-research-system/data/company_profiles`; loaded once per session and normalised to legacy field names so Account Context remains identical to the previous workflow.
- **GWBS cache**: `tools/gwbs_tools` caches per-company/per-scope results with TTL to reduce duplicate Bing calls during the same session.
- **Briefing cache**: `_briefing_cache` in `tools/orchestrators` stores assembled briefings for rapid follow-ups.
- **Conversation context**: `services/conversation_manager` keeps analysis blobs keyed by company + intent.

---

## Error Handling & Fallbacks
- Task executor wraps each coroutine; failures surface as warnings in the final payload without aborting other tasks.
- Intent resolver downgrades to rule-based routing if the SK function errors or returns low confidence.
- Chainlit presenter displays warning banners when tasks fail, ensuring transparency to the user.
- Legacy orchestrator remains available behind a feature toggle for emergency rollback.

---

## Deployment & Configuration
- **Entrypoint**: `launch_chainlit.py` (loads `.env`, configures logging, initialises shared services, spins up Chainlit app).
- **Environment variables**: Azure/OpenAI credentials, `AZURE_BING_CONNECTION_ID`, router/task executor timeouts, cache TTLs (see `env.example`).
- **Logging**: `config/logging_config.py` provides structured logging; Bing agent captures executed queries for audit.
- **Docker**: Existing `Dockerfile` + `docker-compose.yml` remain compatible; enhanced workflow requires no additional services.

---

## Legacy Workflow Parity
- Account Context fields (buyers, opportunities, alumni, overview) remain unchanged to preserve stakeholder experience.
- Legacy single-company workflow can be re-enabled via configuration while the enhanced orchestrator is the default for new requests.

---

## Data Flow Summary
USER (Chainlit) -> `main.py` -> Enhanced Orchestrator -> Intent Plan -> Task Executor ->
  - Company lane -> Bing GWBS scopes -> Analyst Agent
  - General research lane -> Bing topical helpers -> Analyst Agent
  - Follow-up lane -> Cached analyses / targeted Bing
-> Response Formatter -> Chainlit presentation (GWBS appendix -> analyst insights -> account context -> citations).

---

*Last updated: 5 October 2025*
