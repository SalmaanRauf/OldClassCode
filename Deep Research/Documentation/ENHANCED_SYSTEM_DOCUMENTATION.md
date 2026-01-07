# Enhanced Company Intelligence Chat — Technical Notes

## 1. System Overview
The rebuilt Company Intelligence Chat agent is an orchestration-first workflow that accepts free-form requests and delivers company briefings, competitor sweeps, or general research responses with strict citation controls. Core design goals:
- **Intent-aware**: A hybrid router (LLM + rules) decomposes multi-intent prompts into discrete tasks.
- **Evidence-backed**: All facts originate from Azure Bing Grounding annotations and are filtered before presentation.
- **Profile-enriched**: Proprietary relationship data (key buyers, alumni, opportunities) is injected into analysis and surfaced in the UI.
- **Resilient**: Each task runs independently; partial failures are reported without collapsing the whole response.

---

## 2. Component Map
| Layer | Key Modules | Notes |
| --- | --- | --- |
| Chat interface | `chainlit_app/main.py` | Session bootstrap, profile cache, progress signalling, message rendering. |
| Intent resolution | `services/enhanced_router.py`, `sk_functions/Intent_Resolver_prompt.txt` | Classifies requests (company briefing, general research, mixed, follow-up, comparison, clarification). Falls back to rule router on LLM failure. |
| Task orchestration | `tools/orchestrators.py`, `tools/task_executor.py` | Builds per-intent task lists, executes them concurrently, aggregates task outputs. |
| Research execution | `agents/bing_data_extraction_agent.py` | Encapsulates Bing Grounding sessions with corrective re-runs, inline URL scrubbing, and domain filters. Contains specialised search helpers (company any, competitor, market rankings, technology trends, etc.). |
| Analytical processing | `agents/analyst_agent.py`, SK prompts (`FinancialEvent`, `OpportunityIdent`, `EarningsCall`, `StrategicInsight`, `CompanyTakeaway`) | Performs triage, extracts quantitative details, produces consulting insights, normalises scope-level events, leverages profile data. |
| Formatting | `tools/response_formatter.py` | Builds unified payload (summary, events, combined citations, raw GWBS sections). |
| Presentation | `chainlit_app/main.py` | Emits raw research appendix, analyst section, account context, and consolidated sources to the user. |

Supporting utilities: session caching (`services/cache.py`), company profile loader (`services/company_profiles.py`), conversation context manager (`services/conversation_manager.py`).

---

## 3. Request Lifecycle
1. **Session init**: `start()` in `main.py` creates/loads session state, initialises Bing + Analyst agents, loads company profiles from `agentic-research-system/data/company_profiles`, and stores available company list.
2. **Message received**: `_init_singletons()` ensures agents + router exist; `_get_ctx()` retrieves conversation context.
3. **Intent resolution**: `enhanced_router.route()` uses the SK intent resolver + deterministic fallbacks to return an intent payload.
4. **Task planning**: `enhanced_user_request_handler()` translates the intent into one or more tasks (company briefing, comparison, competitor analysis, general research, follow-up).
5. **Parallel execution**: `task_executor.execute_tasks()` launches task coroutines with `asyncio.gather`, applying per-task timeouts and collecting partial failures.
6. **GWBS calls**: Within each task, the Bing agent opens an ephemeral session, runs the composed prompt, performs a corrective follow-up when citations are empty, deduplicates URLs, and captures audit search queries.
7. **Analyst synthesis**: `analyst_synthesis()` (via `AnalystAgent`) triages GWBS summaries, runs SK analysis functions, deduplicates events by scope, merges profile data, and produces insight objects.
8. **Response building**: `response_formatter` composes a standard payload. Chainlit presenter outputs three sections (GWBS appendix → analyst events → account context) plus a consolidated source list and metadata (execution time, confidence).
9. **Follow-ups**: Subsequent questions reuse cached briefings stored in `ConversationContext.analyses`, allowing instant responses without re-querying Bing unless new data is required.

---

## 4. Tasks & Orchestration
| Task | Trigger | Sub-steps |
| --- | --- | --- |
| Company briefing | Default when a company is specified | GWBS scopes: SEC filings, news, procurement, earnings, industry context → Analyst synthesis → Response formatting. |
| Competitor analysis | Mixed intent (e.g., “company + competitors”) | Bing search for competitor landscape → Analyst summary. |
| General research | Non-company or open-ended prompts | Specialised Bing methods (`search_market_overview`, `search_market_rankings`, etc.) → Summarised output with citations. |
| Comparison | Intent resolver returns COMPARISON | Runs company briefing task for each entity; formatter presents structured comparison. |
| Follow-up | Clarifying questions | Uses cached `AnalysisBlob`; optionally triggers targeted Bing refresh (e.g., earnings). |

**Error handling**
- Each task returns `TaskResult(success: bool, error: Optional[str])`.
- Failing tasks log warnings, propagate human-readable notes into the response, and do not prevent other tasks from succeeding.
- GWBS retries include exponential backoff for transient Azure errors.

**Caching**
- `tools/gwbs_tools` TTL-cache stores GWBS scope results per company.
- `tools/orchestrators` caches briefings (company-level) to speed up follow-ups.
- Profile loader caches JSON to avoid re-reading disk per session.

---

## 5. Bing Agent Enhancements
- **System prompt upgrades**: Enforces capture of deal values, consideration mix, timelines, community commitments, and asks the model to note conflicting figures.
- **Method catalogue**: Beyond the base company scopes, additional helpers support market rankings, technology trends, regulatory updates, competitor sweeps, and unrestricted company lookups.
- **Citation hygiene**: `_strip_inline_urls()` removes model-invented links; `_extract_citations()` filters duplicates and excludes banned domains (e.g., `ainvest.com`).
- **Auditability**: `_log_run_steps_bing_queries()` stores executed search queries inside the audit payload.

---

## 6. Analyst Agent Enhancements
- **Profile-aware insights**: `set_profiles()` normalises multiple key variants; `_lookup_company_profile()` performs resilient lookups to feed SK prompts.
- **Event deduplication**: `analyze_all_data()` consolidates financial/procurement/earnings signals by `(company, scope)`.
- **Insight payload**: `generate_insights()` injects profile data (`key_buyers`, `projects`, `protiviti_alumni`) and merges analysis results before calling SK functions.
- **Company takeaway**: `company_takeaway` SK prompt summarises events per company and aligns guidance with internal relationship data.

---

## 7. Output Composition
The formatted payload contains:
1. **Summary** – High-level answer (varies by intent type).
2. **Events** – List of analysis events with insights, impact metadata (need_type, service_line, urgency, priority, timeline, service_categories), and citations.
3. **Raw GWBS** – Original Bing summaries + citation lists per scope for traceability.
4. **Account Context** – Description, overview stats, two key buyers (with contact details and recent wins), up to three alumni, and active opportunities drawn from the profile JSONs.
5. **Citations** – Deduplicated list of URLs across all tasks.
6. **Execution metadata** – Total runtime, intent classification, router confidence, surfaced warnings.

---

## 8. Guardrails & Quality Controls
- **URL allow-listing**: Analyst synthesis only accepts URLs present in GWBS annotations; any `source_urls` generated by prompts are ignored unless they match.
- **Scope coverage**: Bing prompt emphasises quantitative coverage (deal size, dates) to prevent vague summaries.
- **Failure transparency**: Task-level failures inject an error entry in the response; Chainlit surfaces warnings to the user.
- **Profiling privacy**: Profile JSONs are read-only and never exposed outside the Account Context block; sensitive fields can be redacted in the source data if required.

---

## 9. Configuration & Deployment Notes
- **Environment variables**: `PROJECT_ENDPOINT`, `MODEL_DEPLOYMENT_NAME`, `AZURE_BING_CONNECTION_ID`, SK/OpenAI credentials. Optional toggles: `ENABLE_TOOL_ORCHESTRATOR` for fallbacks, cache TTLs via `Config`.
- **Launch**: `launch_chainlit.py` configures logging (`logging_config.setup_logging`), initialises services, and starts Chainlit.
- **Dependencies**: Azure AI Projects SDK, Semantic Kernel, Chainlit, requests stack.
- **Profiles directory**: Expected at `../agentic-research-system/data/company_profiles`. Missing directory logs a warning but does not abort.

---

## 10. Testing & Verification
- **`python -m compileall company_intel_chat`**: sanity check executed as part of dev flow.
- **Manual verification**: Run a company briefing, ensure raw GWBS, events, account context, and citation list appear.
- **Regression considerations**: When modifying prompts or agent logic, validate that: 
  - Inline URLs are still removed.
  - `Account Context` renders buyers/alumni/opportunities.
  - Mixed intent requests trigger the correct task set.
  - Partial failure messaging reaches the user.

---

## 11. Backlog & Ideas
- Profile enrichment (add revenue history, opportunity stages if present).
- Lightweight numeric validator to cross-check large dollar amounts across multiple citations.
- Export endpoints (PDF/PPT/CSV) that consume the formatted response payload.
- Automated smoke tests for the intent router and task executor.

## 12. Deep Research Mode
- **Purpose**: Opt-in workflow that routes user requests through the Azure AI Foundry Deep Research tool (o3-deep-research + Bing Grounding) to deliver multi-hop market analysis with traceable citations.
- **Enablement**: Set `ENABLE_DEEP_RESEARCH=true` and configure `DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME` plus `BING_CONNECTION_NAME` in `.env`. Chainlit exposes a mode selector so users can switch between Standard and Deep pipelines.
- **Runtime Behaviour**: When Deep mode is active the app posts a single status update (“Performing Deep Research…”) and waits for the managed research pipeline to complete before rendering a consolidated report with sections, citations, and run metadata.
- **Logging & Fallbacks**: Run and thread identifiers are logged at INFO. If a Deep Research call fails, the system logs the exception and falls back to the standard GWBS-based orchestrator with a user-facing warning.

---

*Last updated: 29 September 2025*
