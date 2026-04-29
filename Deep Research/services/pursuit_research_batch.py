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
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

from services.account_brief_formatter import format_account_brief_markdown
from services.account_brief_orchestrator import AccountBriefOrchestrator
from services.account_research_input import AccountResearchInput


DEFAULT_FRESHNESS_DIRECTIVE = (
    "Deep account pursuit research. Include a concise company overview, strategy, filings/financial/risk "
    "signals, competitors, customer/contract/procurement signals, likely needs, named leadership, "
    "buyer-center coverage, recent people moves, public relationship hooks, current/upcoming pursuit "
    "triggers, technology/risk/compliance/operations initiatives, and specific analyst follow-ups. "
    "Prioritize last 180 days, especially last 30-90 days. Do not rely on stale 2024-only material "
    "unless it explains a still-active current initiative."
)

BatchProgressCallback = Callable[[Dict[str, Any]], Awaitable[None] | None]


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
        resume: bool = False,
        only_failed: bool = False,
        force: bool = False,
        timeout_seconds: Optional[float] = None,
        progress_callback: Optional[BatchProgressCallback] = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.orchestrator_factory = orchestrator_factory or AccountBriefOrchestrator
        self.concurrency = max(1, min(int(concurrency or 1), 6))
        self.resume = bool(resume)
        self.only_failed = bool(only_failed)
        self.force = bool(force)
        self.timeout_seconds = timeout_seconds if timeout_seconds and timeout_seconds > 0 else None
        self.progress_callback = progress_callback

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
            "skipped": sum(1 for item in results if item.get("status") == "skipped"),
            "results": results,
        }
        (self.output_dir / "batch_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        return summary

    def _effective_concurrency(self, accounts: List[PursuitAccount]) -> int:
        if not accounts:
            return 1
        return self.concurrency

    async def _run_one(self, index: int, account: PursuitAccount) -> Dict[str, Any]:
        slug = account.output_slug or _slugify(account.account_name)
        prefix = f"{index:02d}-{slug}"
        json_path = self.output_dir / f"{prefix}.json"
        markdown_path = self.output_dir / f"{prefix}.md"

        try:
            existing = self._read_existing_status(json_path)
            if not self.force:
                if self.only_failed and existing.get("status") != "failed":
                    await self._emit_progress(index, account, "skipped", "Skipping because this account was not previously failed.")
                    return self._skipped_result(account, json_path, markdown_path, "not_previously_failed")
                if self.resume and existing and existing.get("status") != "failed":
                    await self._emit_progress(index, account, "skipped", "Skipping completed account due to --resume.")
                    return self._skipped_result(account, json_path, markdown_path, "completed_existing_output")

            await self._emit_progress(index, account, "running", "Starting account research.")
            orchestrator = self.orchestrator_factory()
            request = AccountResearchInput(
                account_name=account.account_name,
                raw_input=account.account_name,
                focus_hint=account.focus_hint,
            )
            run_coro = orchestrator.run(
                request,
                industry_key=account.industry_key,
                use_proconnect=account.use_proconnect,
                proconnect_skip_reason=account.proconnect_skip_reason,
            )
            result = (
                await asyncio.wait_for(run_coro, timeout=self.timeout_seconds)
                if self.timeout_seconds
                else await run_coro
            )
            result["batch_context"] = asdict(account)
            self._write_json_atomic(json_path, result)
            markdown = self._format_pursuit_markdown(account, result)
            self._write_text_atomic(markdown_path, markdown)
            await self._emit_progress(index, account, "success", "Account research complete.")
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
            self._write_json_atomic(json_path, error_payload)
            self._write_text_atomic(
                markdown_path,
                f"# {account.account_name}\n\nBatch run failed: {exc}\n",
            )
            await self._emit_progress(index, account, "failed", str(exc))
            return {
                "account_name": account.account_name,
                "campaign": account.campaign,
                "status": "failed",
                "error": str(exc),
                "json_path": str(json_path),
                "markdown_path": str(markdown_path),
                "use_proconnect": account.use_proconnect,
            }

    def _read_existing_status(self, json_path: Path) -> Dict[str, Any]:
        if not json_path.exists():
            return {}
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            return {"status": "failed"}
        if payload.get("status") == "failed":
            return {"status": "failed"}
        if payload.get("type") == "account_brief" or payload.get("synthesis"):
            return {"status": "success"}
        return {"status": str(payload.get("status") or "unknown")}

    @staticmethod
    def _skipped_result(account: PursuitAccount, json_path: Path, markdown_path: Path, reason: str) -> Dict[str, Any]:
        return {
            "account_name": account.account_name,
            "campaign": account.campaign,
            "status": "skipped",
            "skip_reason": reason,
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "use_proconnect": account.use_proconnect,
        }

    @staticmethod
    def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        tmp_path.replace(path)

    @staticmethod
    def _write_text_atomic(path: Path, text: str) -> None:
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(path)

    async def _emit_progress(self, index: int, account: PursuitAccount, status: str, message: str) -> None:
        if not self.progress_callback:
            return
        result = self.progress_callback(
            {
                "index": index,
                "account_name": account.account_name,
                "campaign": account.campaign,
                "status": status,
                "message": message,
                "use_proconnect": account.use_proconnect,
            }
        )
        if asyncio.iscoroutine(result):
            await result

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
        focus_hint=_public_campaign_focus(name=name, campaign=campaign, industry_key=industry_key),
    )


def apply_proconnect_policy(accounts: Iterable[PursuitAccount], policy: str) -> List[PursuitAccount]:
    normalized = str(policy or "default").strip().lower()
    if normalized == "default":
        return list(accounts)
    if normalized not in {"all", "none"}:
        raise ValueError("proconnect policy must be one of: default, all, none")
    output: List[PursuitAccount] = []
    for account in accounts:
        payload = asdict(account)
        if normalized == "all":
            payload["use_proconnect"] = True
            payload["proconnect_skip_reason"] = None
        else:
            payload["use_proconnect"] = False
            payload["proconnect_skip_reason"] = "ProConnect disabled by batch CLI policy."
        output.append(PursuitAccount(**payload))
    return output


def filter_accounts(accounts: Iterable[PursuitAccount], filters: Iterable[str]) -> List[PursuitAccount]:
    filters_normalized = [
        _slugify(item)
        for item in list(filters or [])
        if str(item or "").strip()
    ]
    if not filters_normalized:
        return list(accounts)
    output: List[PursuitAccount] = []
    for account in accounts:
        candidates = {
            _slugify(account.account_name),
            _slugify(account.output_slug or ""),
        }
        if any(filter_value in candidates for filter_value in filters_normalized):
            output.append(account)
    return output


def _public_campaign_focus(*, name: str, campaign: str, industry_key: str) -> str:
    campaign_normalized = str(campaign or "").lower()
    if "metro dc" in campaign_normalized:
        campaign_focus = (
            "New-account pursuit: identify Metro DC footprint, named executives, likely buyer centers, "
            "current public triggers, public relationship hooks, and first-meeting angles."
        )
    elif "enterprise revenue" in campaign_normalized:
        campaign_focus = (
            "Cross-functional expansion pursuit: identify public leadership, buyer centers, current initiatives, "
            "and signals where multiple advisory or staffing-adjacent needs may exist."
        )
    elif "portco" in campaign_normalized or "pe" in campaign_normalized:
        campaign_focus = (
            "Private-equity portfolio-company pursuit: identify ownership context, board or operating partners, "
            "recent investment/M&A signals, management changes, value-creation themes, and buyer centers."
        )
    elif "bcbs" in campaign_normalized:
        campaign_focus = (
            "Health-plan account expansion pursuit: identify payer leadership, technology/risk/compliance/operations "
            "initiatives, regulatory or market pressure, partnerships, and named buyer lanes."
        )
    else:
        campaign_focus = (
            "Target-account pursuit: identify named executives, buyer centers, recent people moves, current public "
            "triggers, public relationship hooks, and concrete analyst follow-ups."
        )
    return f"{campaign_focus} {DEFAULT_FRESHNESS_DIRECTIVE} Company: {name}. Industry context: {industry_key}."


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug or "account"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
