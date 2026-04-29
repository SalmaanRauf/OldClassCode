#!/usr/bin/env python3
"""
Run stakeholder pursuit research as a batch job.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.pursuit_research_batch import (  # noqa: E402
    PursuitResearchBatchRunner,
    apply_proconnect_policy,
    default_stakeholder_pursuit_accounts,
    filter_accounts,
    load_accounts_jsonl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run stakeholder pursuit research batch.")
    parser.add_argument(
        "--accounts-jsonl",
        type=Path,
        help="Optional JSONL file of custom PursuitAccount rows. Defaults to stakeholder target list.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for JSON and markdown reports.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.getenv("PURSUIT_RESEARCH_CONCURRENCY", "1")),
        help="Concurrent account runs. Default 1. Max 6 at batch layer; Deep Research global cap still applies.",
    )
    parser.add_argument(
        "--deep-research-concurrency",
        type=int,
        default=None,
        help=(
            "Actual concurrent Azure Deep Research runs. Defaults to "
            "DEEP_RESEARCH_MAX_CONCURRENT_RUNS or 2. Max 6."
        ),
    )
    parser.add_argument(
        "--account",
        action="append",
        default=[],
        help="Run only a named account or output slug. Repeat for multiple accounts.",
    )
    parser.add_argument(
        "--proconnect-policy",
        choices=["default", "all", "none"],
        default="default",
        help="Override ProConnect use strategy. default uses encoded stakeholder policy.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip accounts with existing successful JSON output in the output directory.",
    )
    parser.add_argument(
        "--only-failed",
        action="store_true",
        help="Only rerun accounts whose existing JSON output is failed.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rerun accounts even when output files already exist.",
    )
    parser.add_argument(
        "--timeout-minutes",
        type=float,
        default=float(os.getenv("PURSUIT_RESEARCH_TIMEOUT_MINUTES", "90")),
        help="Per-account timeout in minutes. Default 90. Use 0 to disable.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write the account plan but do not call ProConnect or Deep Research.",
    )
    parser.add_argument(
        "--skip-auth-preflight",
        action="store_true",
        help="Skip the Azure identity preflight check before launching live Deep Research calls.",
    )
    return parser.parse_args()


async def main_async() -> int:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    batch_concurrency = _bounded_concurrency(args.concurrency, default=1)
    deep_research_concurrency = _bounded_concurrency(
        args.deep_research_concurrency
        if args.deep_research_concurrency is not None
        else os.getenv("DEEP_RESEARCH_MAX_CONCURRENT_RUNS", "2"),
        default=2,
    )
    os.environ["DEEP_RESEARCH_MAX_CONCURRENT_RUNS"] = str(deep_research_concurrency)

    accounts = load_accounts_jsonl(args.accounts_jsonl) if args.accounts_jsonl else default_stakeholder_pursuit_accounts()
    accounts = filter_accounts(accounts, args.account)
    accounts = apply_proconnect_policy(accounts, args.proconnect_policy)
    output_dir = args.output_dir or (
        ROOT
        / "scripts"
        / "output"
        / "pursuit_research"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    plan_path = output_dir / "batch_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "account_count": len(accounts),
                "concurrency": batch_concurrency,
                "deep_research_concurrency": deep_research_concurrency,
                "proconnect_policy": args.proconnect_policy,
                "resume": args.resume,
                "only_failed": args.only_failed,
                "force": args.force,
                "timeout_minutes": args.timeout_minutes,
                "accounts": [account.__dict__ for account in accounts],
            },
            indent=2,
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    print(f"Wrote batch plan: {plan_path}")

    if args.dry_run:
        print("Dry run complete. No research calls executed.")
        return 0

    if not args.skip_auth_preflight:
        print("Checking Azure authentication before launching batch...", flush=True)
        from services.deep_research_client import preflight_deep_research_authentication

        try:
            auth_status = await preflight_deep_research_authentication()
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(
            "Azure authentication preflight passed "
            f"(scope={auth_status.get('scope')}, expires_on={auth_status.get('expires_on')}).",
            flush=True,
        )

    async def progress(event):
        print(
            "[{index}] {status}: {account_name} | {message}".format(
                index=event.get("index"),
                status=str(event.get("status") or "").upper(),
                account_name=event.get("account_name"),
                message=event.get("message"),
            ),
            flush=True,
        )

    print(
        f"Running {len(accounts)} account(s) with account_concurrency={batch_concurrency}, "
        f"deep_research_concurrency={deep_research_concurrency}"
    )
    runner = PursuitResearchBatchRunner(
        output_dir=output_dir,
        concurrency=batch_concurrency,
        resume=args.resume,
        only_failed=args.only_failed,
        force=args.force,
        timeout_seconds=(args.timeout_minutes * 60) if args.timeout_minutes else None,
        progress_callback=progress,
    )
    summary = await runner.run(accounts)
    print(
        f"Batch complete: {summary['succeeded']} succeeded, "
        f"{summary['failed']} failed, {summary.get('skipped', 0)} skipped"
    )
    print(f"Output directory: {summary['output_dir']}")
    print(f"Summary: {Path(summary['output_dir']) / 'batch_summary.json'}")
    return 0 if summary["failed"] == 0 else 1


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


def _bounded_concurrency(value, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, 6))


if __name__ == "__main__":
    main()
