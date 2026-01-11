# BD Tool — Agent Handoff Document

## Project Overview

**BD Tool** (formerly "Deep Research") is a business development research assistant for **Protiviti**. It helps identify consulting opportunities by researching companies and detecting "signals" (compliance deadlines, regulatory actions, technology shifts, etc.) that indicate a need for Protiviti's services.

### Core Technologies
- **Azure AI Foundry Deep Research** — Bing Grounding for web research
- **Semantic Kernel** — LLM calls via ATLAS/Azure OpenAI
- **Chainlit** — Chat UI framework (version >=1.0.0)

---

## Architecture

### Key Directories
```
BD Tool/
├── chainlit_app/main.py      # Main Chainlit UI
├── services/
│   ├── deep_research_client.py  # Azure Deep Research integration
│   ├── prompt_generator.py      # SK-based prompt generation
│   └── prompt_loader.py         # Loads industry prompts
├── prompts/
│   ├── industries/              # Signal reference manuals (defense.md, etc.)
│   └── signal_registry.json     # GUI options for signals, service lines
├── sk_functions/                # Semantic Kernel prompt templates
├── public/elements/             # Chainlit CustomElement JSX components
└── config/                      # Configuration and kernel setup
```

### Signal-Driven Architecture
1. **System prompts** (`prompts/industries/*.md`) are comprehensive "reference manuals" — each signal has definition, keywords, and research guidance
2. **GUI generates user prompts** — user fills form, LLM creates focused research query
3. **Research executes** with industry context from system prompt

---

## User (Salmaan) Preferences

### Git Commits
- **Separate commits** for each logical feature/change
- **Human-readable messages** (not auto-generated)
- **Include folder paths** when mentioning commits (e.g., "Pushed to `Deep Research/chainlit_app/`")

### Development Style
- **Quality over speed** — "take a step back and think carefully"
- **Verify APIs before implementing** — check actual docs, don't assume
- **Ask questions** when uncertain rather than making assumptions

### UX Decisions
- **No auto-run** — generate prompt, let user copy/paste/edit, then manually run
- **Visual forms preferred** — use CustomElement JSX, not ChatSettings (hidden panel)

---

## Chainlit-Specific Knowledge

### AskElementMessage (Forms)
```python
# CORRECT — 'element' is singular
response = await cl.AskElementMessage(
    content="...",
    element=form_element,  # NOT elements=[...]
    timeout=300
).send()

# Response fields are directly accessible
if response and response.get("submitted"):
    value = response.get("field_name")
```

### CustomElement JSX
- Files go in `public/elements/`
- Use `submitElement(values)` to submit, `cancelElement()` to cancel
- Can use shadcn/ui components (`@/components/ui/*`)

### ChatSettings
- Creates a hidden settings panel (gear icon)
- **Not recommended** for visible forms — use CustomElement instead

---

## Current State (as of 2026-01-07)

### Implemented Features
- ✅ Industry-specific signal reference prompts (defense, financial services, healthcare, energy, technology, general)
- ✅ Signal registry JSON for GUI options
- ✅ Research parameter form (CustomElement with sector dropdown, text inputs)
- ✅ Prompt generator service (SK-based)
- ✅ "Other context" field for additional user instructions
- ✅ Copy/paste prompt flow (user edits before running)

### Known Limitations
- Chainlit cannot programmatically set chat input — requires copy/paste

---

## Environment Variables
Key vars needed (from `.env`):
- `OPENAI_API_KEY` / `AZURE_OPENAI_*` — LLM access
- `PROJECT_ENDPOINT`, `PROJECT_ID` — Azure AI Foundry
- `AZURE_BING_CONNECTION_ID` — Bing Grounding
- `ENABLE_DEEP_RESEARCH=true` — Feature flag

---

## Quick Start
```bash
cd BD\ Tool
pip install -r requirements.txt
chainlit run chainlit_app/main.py --host 0.0.0.0 --port 8000
```
