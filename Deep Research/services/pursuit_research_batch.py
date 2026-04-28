"""
Batch pursuit-research runner for stakeholder target accounts.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from services.account_brief_formatter import format_account_brief_markdown
from services.account_brief_orchestrator import AccountBriefOrchestrator
from services.account_research_input import AccountResearchInput


DEFAULT_FRESHNESS_DIRECTIVE = (
    "Prioritize last 180 days, especially last 30-90 days. "
    "Find current/upcoming pursuit triggers, leadership and buyer-center signals, "
    "technology/risk/compliance/operations initiatives, procurement or contract activity, "
    "and analyst follow-ups. Do not rely on stale 2024-only material unless it explains "
    "a still-active current initiative."
)


@dataclass(frozen=True)
class PursuitAccount:
    account_name: str
    campaign: str
    focus_hint: str
    industry_key: Optional[str] = None
    use_proconnect: bool = True
    proconnect_skip_reason: Optional[str] = None
    output_slug: Optional[str] = None


class PursuitResearchBatchRunner:
    """Run account brief research for multiple stakeholder target accounts."""

    def __init__(
        self,
        *,
        output_dir: Path | str,
        orchestrator_factory: Callable[[], Any] | None = None,
        concurrency: int = 1,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.orchestrator_factory = orchestrator_factory or AccountBriefOrchestrator
        self.concurrency = max(1, min(int(concurrency or 1), 2))

    async def run(self, accounts: Iterable[PursuitAccount]) -> Dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        account_list = list(accounts or [])
        effective_concurrency = self._effective_concurrency(account_list)
        semaphore = asyncio.Semaphore(effective_concurrency)
        started_at = _utc_timestamp()

        async def _run_one(index: int, account: PursuitAccount) -> Dict[str, Any]:
            async with semaphore:
                return await self._run_one(index, account)

        results = await asyncio.gather(
            *[_run_one(index, account) for index, account in enumerate(account_list, 1)]
        )
        summary = {
            "started_at": started_at,
            "completed_at": _utc_timestamp(),
            "output_dir": str(self.output_dir),
            "requested_concurrency": self.concurrency,
            "concurrency": effective_concurrency,
            "total": len(results),
            "succeeded": sum(1 for item in results if item.get("status") == "success"),
            "failed": sum(1 for item in results if item.get("status") == "failed"),
            "results": results,
        }
        (self.output_dir / "batch_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        return summary

    def _effective_concurrency(self, accounts: List[PursuitAccount]) -> int:
        industry_keys = {
            str(account.industry_key or "general").strip().lower() or "general"
            for account in accounts
        }
        # The Deep Research client is currently process-global by prompt config.
        # Keep mixed-industry batches sequential to avoid client churn mid-run.
        if len(industry_keys) > 1:
            return 1
        return self.concurrency

    async def _run_one(self, index: int, account: PursuitAccount) -> Dict[str, Any]:
        slug = account.output_slug or _slugify(account.account_name)
        prefix = f"{index:02d}-{slug}"
        json_path = self.output_dir / f"{prefix}.json"
        markdown_path = self.output_dir / f"{prefix}.md"

        try:
            orchestrator = self.orchestrator_factory()
            request = AccountResearchInput(
                account_name=account.account_name,
                raw_input=account.account_name,
                focus_hint=account.focus_hint,
            )
            result = await orchestrator.run(
                request,
                industry_key=account.industry_key,
                use_proconnect=account.use_proconnect,
                proconnect_skip_reason=account.proconnect_skip_reason,
            )
            result["batch_context"] = asdict(account)
            json_path.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")
            markdown = self._format_pursuit_markdown(account, result)
            markdown_path.write_text(markdown, encoding="utf-8")
            return {
                "account_name": account.account_name,
                "campaign": account.campaign,
                "status": "success",
                "json_path": str(json_path),
                "markdown_path": str(markdown_path),
                "use_proconnect": account.use_proconnect,
            }
        except Exception as exc:
            error_payload = {
                "account": asdict(account),
                "status": "failed",
                "error": str(exc),
            }
            json_path.write_text(json.dumps(error_payload, indent=2, ensure_ascii=True), encoding="utf-8")
            markdown_path.write_text(
                f"# {account.account_name}\n\nBatch run failed: {exc}\n",
                encoding="utf-8",
            )
            return {
                "account_name": account.account_name,
                "campaign": account.campaign,
                "status": "failed",
                "error": str(exc),
                "json_path": str(json_path),
                "markdown_path": str(markdown_path),
                "use_proconnect": account.use_proconnect,
            }

    @staticmethod
    def _format_pursuit_markdown(account: PursuitAccount, result: Dict[str, Any]) -> str:
        base = format_account_brief_markdown(
            company_name=str(result.get("company") or account.account_name),
            synthesis=dict(result.get("synthesis") or {}),
            proconnect_summary=dict(result.get("proconnect_summary") or {}),
            deep_research_summary=dict(result.get("deep_research_summary") or {}),
        )
        header = [
            f"# {account.account_name} Pursuit Research",
            "",
            f"Campaign: {account.campaign}",
            f"Research posture: {'Public research + ProConnect' if account.use_proconnect else 'Public research only'}",
            f"Freshness directive: {DEFAULT_FRESHNESS_DIRECTIVE}",
            "",
            "---",
            "",
        ]
        return "\n".join(header + [base]).strip() + "\n"


def default_stakeholder_pursuit_accounts() -> List[PursuitAccount]:
    """Accounts from the stakeholder target-account message with POC run posture."""
    return [
        _account("BAE Systems", "Metro DC Target Accounts", "defense", False, "Stakeholder identified no known work / no MSA."),
        _account("Total Wine & More", "Metro DC Target Accounts", "general", False, "Stakeholder identified no known work / no MSA."),
        _account("Genworth Financial", "Metro DC Target Accounts", "financial_services", False, "Stakeholder identified no known work / no MSA."),
        _account("Danaher", "Enterprise Revenue Acceleration", "general", True, None),
        _account("CareFirst BlueCross BlueShield", "Enterprise Revenue Acceleration", "healthcare", True, None),
        _account("District of Columbia Housing Authority", "Enterprise Revenue Acceleration", "general", False, "Stakeholder identified RHI work but no known Protiviti work."),
        _account("Apex Tool Group", "PE and PortCo Campaign", "general", False, "Public PortCo unlock research prioritized for this POC."),
        _account("Iron Bow Technologies", "PE and PortCo Campaign", "technology", False, "Public PortCo unlock research prioritized for this POC."),
        _account("Empower AI", "PE and PortCo Campaign", "technology", False, "Public PortCo unlock research prioritized for this POC."),
        _account("Unchained Entertainment", "PE and PortCo Campaign", "technology", False, "Public PortCo unlock research prioritized for this POC."),
        _account("Cloudpermit", "PE and PortCo Campaign", "technology", False, "Public PortCo unlock research prioritized for this POC."),
        _account("Sayari", "PE and PortCo Campaign", "technology", False, "Public PortCo unlock research prioritized for this POC."),
        _account("Blue Cross Blue Shield of Massachusetts", "BCBS System PGP Elite Program", "healthcare", True, None),
        _account("Blue Cross Blue Shield of North Carolina", "BCBS System PGP Elite Program", "healthcare", True, None),
        _account("CareFirst BlueCross BlueShield", "BCBS System PGP Elite Program", "healthcare", True, None, "carefirst-bcbs-pgp"),
        _account("Blue Cross Blue Shield of South Carolina", "BCBS System PGP Elite Program", "healthcare", True, None),
        _account("Blue Cross Blue Shield of Tennessee", "BCBS System PGP Elite Program", "healthcare", True, None),
    ]


def load_accounts_jsonl(path: Path | str) -> List[PursuitAccount]:
    accounts: List[PursuitAccount] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        payload = json.loads(line)
        try:
            accounts.append(PursuitAccount(**payload))
        except TypeError as exc:
            raise ValueError(f"Invalid account row at line {line_number}: {exc}") from exc
    return accounts


def _account(
    name: str,
    campaign: str,
    industry_key: str,
    use_proconnect: bool,
    skip_reason: Optional[str],
    output_slug: Optional[str] = None,
) -> PursuitAccount:
    return PursuitAccount(
        account_name=name,
        campaign=campaign,
        industry_key=industry_key,
        use_proconnect=use_proconnect,
        proconnect_skip_reason=skip_reason,
        output_slug=output_slug,
        focus_hint=f"{campaign}. {DEFAULT_FRESHNESS_DIRECTIVE}",
    )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug or "account"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
