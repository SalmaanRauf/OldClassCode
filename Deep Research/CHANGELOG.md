# Changelog

All notable changes to this package are documented here. Dates use YYYY‑MM‑DD.

## Unreleased

- Async-safe GWBS orchestration:
  - Offload all GWBS (Bing Grounding) calls to background threads to keep Chainlit responsive.
  - Run multiple scopes concurrently (SEC, News, Procurement, Earnings, Industry) where appropriate.
  - Apply per-scope timeouts (45s) with graceful degradation when any scope fails.
- Streaming progress for new analysis:
  - Emits per-scope messages (e.g., “✅ Collected: News”) as each section completes.
- Centralized question classifier:
  - Added `services/classifier.py` for a single source of truth on labels, scope mapping, and when synthesis is required.
  - Refactored router (`services/conversation_manager.py`), orchestrators (`tools/orchestrators.py`), and legacy follow-up (`services/follow_up_handler.py`) to use the centralized classifier.
- General request handling after briefing:
  - Multi-intent inputs (e.g., briefing + “risk/competitors/strategy”) are handled by the unified follow-up pipeline immediately after the briefing.
- Public API for competitor research:
  - Added `search_competitors` to `agents/bing_data_extraction_agent.py` (replacing private method usage) and updated tools to call it.
- Python compatibility:
  - Replaced `str | None` with `Optional[str]` in `chainlit_app/main.py` to support Python 3.9.
- Documentation updates:
  - Expanded `company_intel_chat/README.md` to include the above improvements.

## 2025-XX-XX — Initial extraction

- Created `company_intel_chat/` as a clean, self‑contained package for the Chainlit chat use case.
- Contents include:
  - Chainlit app (`chainlit_app/`), agents (`agents/`), services (`services/`), tools (`tools/`), models (`models/`), config (`config/`), and SK prompts (`sk_functions/`).
  - `launch_chainlit.py`, `requirements.txt`, and `env.example` for quick setup.
- Implemented tool-centric architecture for GWBS + Semantic Kernel analysis.
