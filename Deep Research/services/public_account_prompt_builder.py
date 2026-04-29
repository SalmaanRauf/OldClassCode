"""
Prompt composition for public-account Deep Research runs.
"""
from __future__ import annotations

from datetime import date
from dataclasses import dataclass

from services.prompt_loader import PromptLoader


PUBLIC_ACCOUNT_SYSTEM_PROMPT = """
# Public Account Pursuit Research

You are a public-web research analyst building a deep target-account pursuit dossier for senior commercial leaders.

This prompt supersedes any generic industry report or citation-volume pattern. The goal is a compact, current, source-grounded pursuit research package that helps a managing director understand the company, why it may need help now, who to pursue, what to ask for, and what analyst follow-up is needed.

Use only publicly accessible information: company sites, leadership pages, investor materials, filings, regulator/government records, procurement records, reputable news, credible trade press, public executive biographies, and public professional profiles when available.

Do not mention, assume, or infer any private sales system, private delivery history, private account status, private buyer history, private relationship route, or private sales activity. Do not name the seller organization. Keep public facts separate from clearly labeled public-web hypotheses.

Freshness is mandatory:
- Prioritize evidence from the last 180 days.
- Give special weight to the last 30-90 days.
- Use older material only when it explains a still-active initiative or a current leader's background.
- Label old-only evidence as stale and not sufficient for an active pursuit.

Build both account context and people context:
- Give a useful company overview: business model, revenue/segment mix if public, geography, customer/end-market exposure, ownership, and current strategic direction.
- For public companies, scan current and recent SEC filings such as 10-K, 10-Q, 8-K, proxy statements, investor presentations, earnings calls, and risk factors. For private/nonprofit/government-adjacent entities, use equivalent public reports, bond/municipal disclosures, regulator filings, procurement records, press releases, and reputable news.
- Explain competitive position, major competitors/substitutes, customer concentration or contract exposure when public, and external pressure from regulation, market shifts, cost, technology, security, workforce, or operations.
- Translate the research into likely needs and white-space hypotheses, clearly labeled as hypotheses unless directly sourced.
- Identify named executives, likely buying-committee members, board/PE/operating stakeholders, and public leadership changes.
- Cover C-suite, finance, technology, cyber/security, legal/compliance/risk, operations, procurement, transformation, and relevant business-unit leaders where public evidence supports it.
- If a true reporting hierarchy is unavailable, provide a public buyer-center map and state the gap.

Return concise Markdown with the exact section headings requested by the user. Use tables where requested. Every row should include a date, source, or explicit evidence limitation when possible.
""".strip()


INDUSTRY_SOURCE_GUIDANCE = {
    "defense": (
        "Prioritize SAM.gov, FPDS/USAspending, GAO, agency and program offices, "
        "CMMC/DFARS/NIST signals, contract awards, defense trade press, and public "
        "executive/program leadership."
    ),
    "healthcare": (
        "Prioritize company leadership pages, plan/provider regulatory filings, CMS, "
        "state insurance regulators, NAIC where relevant, quality/cost/access initiatives, "
        "technology modernization, payer-provider partnerships, and executive changes."
    ),
    "financial_services": (
        "Prioritize SEC filings, investor relations, earnings materials, regulator actions, "
        "risk/compliance signals, technology and data modernization, ratings/analyst coverage, "
        "and finance/risk/technology leadership."
    ),
    "technology": (
        "Prioritize company newsroom/blogs, product and security announcements, customer/partner "
        "news, funding or ownership context, public leadership pages, hiring signals, and cyber/data "
        "or platform modernization indicators."
    ),
    "energy": (
        "Prioritize investor materials, regulator/environmental filings, operational safety, "
        "asset/infrastructure investment, grid/energy-transition initiatives, and executive moves."
    ),
    "general": (
        "Prioritize official company materials, leadership pages, filings if available, regulator "
        "or procurement records, reputable news, trade press, public hiring/procurement signals, "
        "and named executives tied to current initiatives."
    ),
}


@dataclass(frozen=True)
class PublicAccountPromptPackage:
    industry_key: str
    system_prompt: str
    user_prompt: str


class PublicAccountPromptBuilder:
    """Compose Deep Research prompts for public-account research."""

    def __init__(self, prompt_loader: PromptLoader | None = None) -> None:
        self.prompt_loader = prompt_loader or PromptLoader()

    def build(
        self,
        *,
        company_name: str,
        focus_hint: str | None = None,
        industry: str | None = None,
        as_of_date: str | None = None,
    ) -> PublicAccountPromptPackage:
        resolved_company = str(company_name or "").strip()
        if not resolved_company:
            raise ValueError("company_name is required")

        industry_key = self._select_industry(industry)
        # Keep Deep Research blind to private account systems and seller-specific context.
        # The industry files are broad BD prompts; this public mode uses only the
        # resolved industry key plus public source guidance.
        system_prompt = self._build_system_prompt(industry_key)
        return PublicAccountPromptPackage(
            industry_key=industry_key,
            system_prompt=system_prompt,
            user_prompt=self._build_user_prompt(
                company_name=resolved_company,
                focus_hint=focus_hint,
                industry_key=industry_key,
                include_industry_context=bool(str(industry or "").strip()),
                as_of_date=as_of_date or date.today().isoformat(),
            ),
        )

    def _select_industry(self, industry: str | None) -> str:
        if str(industry or "").strip():
            resolved = self.prompt_loader.resolve_industry_key(industry)
            if resolved:
                return resolved
        return "general"

    def _build_system_prompt(self, industry_key: str) -> str:
        guidance = INDUSTRY_SOURCE_GUIDANCE.get(industry_key, INDUSTRY_SOURCE_GUIDANCE["general"])
        return (
            f"{PUBLIC_ACCOUNT_SYSTEM_PROMPT}\n\n"
            f"## Industry Source Guidance\n"
            f"Industry: {self._format_industry_label(industry_key)}\n"
            f"{guidance}"
        ).strip()

    def _build_user_prompt(
        self,
        *,
        company_name: str,
        focus_hint: str | None,
        industry_key: str,
        include_industry_context: bool,
        as_of_date: str,
    ) -> str:
        lines = [
            f"Build a public-account research brief for an upcoming pursuit at {company_name}.",
            "",
            "## Scope",
            f"Company: {company_name}",
            f"Current as of: {as_of_date}",
        ]
        if include_industry_context:
            lines.append(f"Industry: {self._format_industry_label(industry_key)}")
        normalized_focus_hint = str(focus_hint or "").strip()
        if normalized_focus_hint:
            lines.append(f"Focus hint: {normalized_focus_hint}")
        lines.extend(
            [
                "",
                "## Required Output",
                "Use these exact Markdown section headings:",
                "",
                "## Executive Pursuit Thesis",
                "2-4 sentences on the most actionable public thesis for a senior pursuit leader.",
                "",
                "## Company Snapshot",
                "Concise overview of what the company does, ownership/public status, scale if publicly available, main segments/products/services, geography, customer/end-market exposure, and current strategic posture.",
                "",
                "## Strategy, Priorities, and Operating Pressure",
                "Bullets covering strategic priorities, transformation programs, cost/margin pressure, growth initiatives, operational constraints, regulatory pressure, technology/cyber/security pressure, workforce issues, or other current business drivers.",
                "",
                "## Filings, Financials, and Risk Signals",
                "Markdown table with columns: Source/date | Signal | Why it matters | Pursuit implication.",
                "For public companies, scan recent 10-K, 10-Q, 8-K, proxy, investor presentations, earnings calls, and risk factors. For non-public entities, use equivalent public reports, regulatory records, procurement records, bond/municipal disclosures, press releases, and reputable news.",
                "",
                "## Competitive and Market Context",
                "Bullets covering main competitors/substitutes, market position, market disruption, pricing/cost pressure, customer demand shifts, regulatory/technology trends, and where the company may be trying to differentiate.",
                "",
                "## Customer, Contract, and Procurement Signals",
                "Bullets covering major customers, government contracts, procurement activity, partnerships, vendor ecosystem, contract recompetes, implementation programs, or other buying/procurement clues when public.",
                "",
                "## Likely Needs / White-Space Hypotheses",
                "Markdown table with columns: Need or hypothesis | Evidence | Likely buyer lane | Confidence | Analyst validation step.",
                "Clearly label hypotheses. Tie needs to evidence such as filings, strategy, contracts, people moves, risks, or current initiatives.",
                "",
                "## People to Pursue",
                "Markdown table with columns: Person | Current role | Buyer lane | Why this person matters now | Evidence date/source.",
                "Only include named people with public evidence. Include C-suite, finance, technology, security, legal/compliance/risk, operations, procurement, transformation, board/ownership, and business-unit leaders when available.",
                "",
                "## Recent People Moves",
                "Markdown table with columns: Person | Move | Date | Why it matters | Source.",
                "Focus on appointments, promotions, departures, board changes, PE operating roles, and newly empowered leaders from the last 18 months. Prioritize last 180 days.",
                "",
                "## Buying Committee Map",
                "Markdown table with columns: Buyer role | Named person or public role | Evidence | Likely concern | Follow-up needed.",
                "Map economic/executive, user/operator, technical, finance/procurement, legal/compliance/risk, security, and potential coach lanes. Use role-level hypotheses only when names are unavailable.",
                "",
                "## Why Now / Current Triggers",
                "Bullets with date, trigger, pursuit relevance, and source. Prioritize last 30-90 days, then last 180 days.",
                "",
                "## Recent Initiatives / Public Signals",
                "Bullets covering investments, transformation, technology, cyber/security, risk/compliance, procurement, M&A, partnerships, cost/performance pressure, filings, or market events.",
                "",
                "## Public Relationship Hooks / Warm-Path Hypotheses",
                "Bullets based only on public information such as alumni paths, board overlap, prior employers, associations, geography, partners, or ecosystem links. Label each as a hypothesis unless directly sourced.",
                "",
                "## Recommended MD Actions This Week",
                "3-5 concrete actions. Each action should name the person/role to pursue, the reason, and the requested analyst follow-up or introduction path.",
                "",
                "## Coverage Gaps",
                "Bullets for missing hierarchy, missing recent evidence, no public buyer name, stale-only evidence, or uncertain ownership.",
                "",
                "## Sources",
                "Working URLs grouped by source type. Prefer 8-12 high-quality current sources over a forced high-volume source list.",
                "",
                "## Research Standard",
                "Use explicit section headings and preserve source-backed evidence throughout the report.",
                "Do not rely on stale 2024-only material unless it directly explains a still-active current initiative.",
                "If current public evidence is thin, say that directly and make analyst follow-up specific.",
            ]
        )
        return "\n".join(lines).strip()

    @staticmethod
    def _format_industry_label(industry_key: str) -> str:
        return (industry_key or "general").replace("_", " ").title()
