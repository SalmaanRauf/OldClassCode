# Company Intelligence Chat - Stakeholder Guide

## 1. Architecture at a Glance
To make the new workflow easy to understand, think of the system as a concierge who listens to a request, breaks it into jobs, and coordinates experts to deliver a polished briefing. Each layer keeps the experience fast, factual, and tailored to account teams.

**Narrative walk-through**
1. A stakeholder types a question in Chainlit. The app remembers who is asking, which companies are in play, and loads known account data.
2. The orchestrator interprets the question, asking an AI planner to classify the request (briefing, competitors, general research) and double-checking the answer with simple rules so nothing falls through.
3. For each required job, the orchestrator spins up a mini task: gather market evidence, fetch company filings, or reuse earlier answers. Tasks run in parallel so the user sees progress as soon as possible.
4. Specialist agents do the hard work. The Bing research agent pulls fresh, cited evidence; the analyst agent reads it, extracts important facts, and blends in relationship intel from the account profile with more focused insights.
5. The response formatter stitches everything into the format teams expect: raw research, analyst insight, and the Account Context block that mirrors the legacy briefing.
6. Chainlit streams progress updates ("collecting earnings info", "analyzing findings") and then posts the final answer, complete with citations and follow-up guidance.

**What each layer solves**
| Layer | Plain-language role | Why it matters |
| --- | --- | --- |
| Chainlit UI | Welcomes the user, remembers session context, and shows progress. | Keeps the experience familiar while signaling what is happening behind the scenes. |
| Enhanced orchestrator | Project manager that plans the work and safety-checks the plan. | Prevents missed intents, supports mixed requests, and guarantees a fallback path. |
| Task lanes | Parallel runners for company, competitor, and general research jobs. | Delivers answers quickly and keeps unrelated work from blocking the rest. |
| Research agents | Specialists that gather evidence from Bing or cached results. | Ensures every fact is backed by a citation and auto-recovers from empty searches. |
| Analyst agent | Consultant who turns evidence into insights and ties in account data. | Maintains the same Account Context richness while adding curated insights. |
| Response formatter | Editor who assembles the deliverable. | Guarantees consistent structure, clean citations, and reusable payloads. |
| Chainlit presenter | Final mile delivery with streaming updates and structured output. | Gives stakeholders confidence, highlights warnings, and invites follow-up questions. |

**Technical flow reference**
```
User (Chainlit UI)
    |
    v
chainlit_app/main.py
    |  |- session + profile bootstrap
    |  \- delegates to enhanced orchestrator
    v
Enhanced orchestrator (tools/orchestrators)
    |  |- Intent resolver (services/enhanced_router, intent_resolver SK function)
    |  \- Task executor (tools/task_executor)
    v
Task lanes (async)
    |  |- Company briefing -> Bing GWBS scopes -> Analyst agent
    |  |- General research -> General research orchestrator -> Bing topical helpers
    |  \- Follow-up reuse -> Cached briefings / targeted Bing refresh
    v
Response formatter (tools/response_formatter)
    |  \- Builds summary, events, raw GWBS, account context, citations, metadata
    v
Chainlit presenter
    |- Streams progress + partial results
    \- Sends final structured response blocks
```

---

## 2. Purpose & Outcomes
The rebuilt Company Intelligence Chat delivers consultant-grade briefings, competitor sweeps, and open-ended research through a conversational interface. Each run fuses live market evidence, analyst-grade synthesis, and proprietary relationship data so engagement teams can pivot directly into client action.

**What stakeholders receive**
- An executive-ready narrative with analyst commentary and cited facts
- A raw research appendix (Bing Grounding summaries + audit metadata)
- An "Account Context" block that mirrors the legacy experience (buyers, opportunities, alumni, overview stats)
- Follow-on Q&A chained to the same evidence base, with cached context for speed
- Optional general-research digests when the ask is not company-specific

---

## 3. End-to-End User Flow
1. **User submits a request in Chainlit** (e.g., "Brief Capital One and compare to Discover").
2. **Session preparation** (`chainlit_app/main.py`): load or create session state, hydrate company profiles, initialise Bing + analyst agents, and attach progress hooks.
3. **Intent resolution** (`services/enhanced_router` + `services/intent_resolver`): the Semantic Kernel intent function proposes an execution plan; deterministic rules backstop low-confidence LLM results.
4. **Task planning** (`tools/orchestrators.enhanced_user_request_handler`): translate the intent plan into concrete tasks (company briefing, competitor sweep, general research, follow-up) and align required agents.
5. **Parallel task execution** (`tools/task_executor`): run company, competitor, and research tasks concurrently, enforcing per-task timeouts and capturing partial failures.
6. **Data acquisition**:
   - Company tasks call the Bing GWBS agent (`agents/bing_data_extraction_agent`) across SEC, news, procurement, earnings, and industry scopes.
   - General research tasks leverage the dedicated orchestrator (`tools/general_research_orchestrator`) and the Bing agent's new topical helpers (market overview, regulatory updates, technology trends, etc.).
7. **Analyst synthesis** (`agents/analyst_agent` + SK prompts): triage GWBS results, extract quantitative facts, merge company profile data, and produce consulting insights.
8. **Response assembly** (`tools/response_formatter`): combine summaries, analyst events, raw GWBS output, account context, citations, and runtime metadata into a unified payload.
9. **Presentation** (`chainlit_app/main.py`): stream progress, then deliver GWBS appendix -> analyst view -> account context -> citation bundle. Follow-up prompts reuse cached briefings unless new data is required.

---

## 4. Current Capabilities
| Capability | Description |
| --- | --- |
| Any-company briefing | Full GWBS + analyst pipeline for any named company (no allowlist). |
| Mixed intent handling | Router decomposes prompts spanning companies, competitors, and free-form research. |
| Evidence-first answers | Every claim is backed by a Bing citation; inline model-invented URLs are stripped. |
| Proprietary relationship context | Account Context reuses legacy profile fields (buyers, alumni, opportunities) and injects them into SK prompts. |
| General research digests | Dedicated orchestrator covers market overviews, regulatory updates, technology trends, and location-based financial scans. |
| Follow-up support | Cached briefings and analysis blobs power rapid, intent-aware clarifications. |

---

## 5. Data Inputs & Guardrails
| Source | Use | Guardrails |
| --- | --- | --- |
| Azure Bing Grounding | Primary factual research (company + topical) | Domain filters, inline URL stripping, corrective reruns when citations absent. |
| `agentic-research-system/data/company_profiles` | Buyers, opportunities, alumni, overview stats | Normalised keys, read-only cache, strict parity with legacy Account Context fields. |
| Conversation context cache | Follow-ups and mixed prompts | Stored per session; revalidated against latest intent plan before reuse. |
| App configuration (`config.Config`) | Timeouts, cache TTL, feature toggles | Defaults keep enhanced flow opt-in; legacy flow remains as fallback switch. |

**Quality controls**
- Task-level error reporting keeps partial results while flagging failures to the UI.
- Citation allow-listing ensures analyst outputs only reference GWBS-provided links.
- Scope deduplication prevents repetitive events for the same company + scope pair.
- Cached briefings expire after 30 minutes to avoid stale insights.

---

## 6. Cognitive Components & Prompts
| Component | Purpose |
| --- | --- |
| `intent_resolver` SK function | LLM-based intent classification with reasoning, backed by rule router. |
| Analyst SK prompts (`FinancialEvent`, `OpportunityIdent`, `EarningsCall`, `StrategicInsight`, `CompanyTakeaway`) | Extract quantitative facts, map impacts, craft consulting angles.|
| `triage` prompt | Filters GWBS sections to the most relevant items before downstream analysis. |
| Bing agent system prompt | Enforces quantitative pull-through (deal values, timelines, conflicts) and citation hygiene. |

Prompts leverage account context fields (buyers, alumni, opportunities) to ground recommendations and highlight client-specific hooks.

---

## 7. Output Structure
1. **Raw Research Appendix** - Section-by-section GWBS summaries with citations and audit metadata.
2. **Analyst Events & Insights** - High-impact events, implications, consulting angles, and recommended service lines.
3. **Account Context** - Description, topline metrics, key buyers, alumni, and active opportunities, mirroring the legacy briefing format.
4. **General Research Blocks** - When applicable, topical findings with cited sources and clear scope labels.
5. **Citation Bundle & Runtime Metadata** - Deduplicated URL list, intent classification, execution time, and surfaced warnings.

---

## 8. Configuration & Deployment
- **Environment variables**: `PROJECT_ENDPOINT`, `MODEL_DEPLOYMENT_NAME`, `AZURE_BING_CONNECTION_ID`, SK/OpenAI credentials, plus cache + feature toggles (see `env.example`).
- **Launch path**: `launch_chainlit.py` loads `.env`, configures logging, initialises shared services, and starts Chainlit.
- **Caching**: `tools/gwbs_tools` (GWBS scope cache), `tools/orchestrators` (briefing cache), `services/company_profiles` (profile cache).
- **Fallbacks**: Feature flagging keeps the legacy orchestrator available should enhanced routing be disabled.

---

## 9. Testing & Observability
- **Static checks**: `python -m compileall company_intel_chat` plus import validation for new modules.
- **Manual smoke flows**: Company briefing, mixed prompt, general research-only, and follow-up scenarios exercised post-release.
- **Logging**: Structured logging via `config/logging_config.py`, including task-level warnings and Bing audit trails.
- **Progress telemetry**: Chainlit progress events surface scope-level completion counts and cite totals during execution.

---

## 10. Future Enhancements
- Expand Account Context with spend history and opportunity stages when data is available.
- Add automated regression tests around intent planning and task execution.
- Introduce lightweight numeric cross-checks for large financial figures.
- Provide export utilities (PDF / PowerPoint) powered by the unified response payload.
- Layer in performance dashboards (latency, cache hit rate, task failure ratios).

---

*Last updated: 5 October 2025*
