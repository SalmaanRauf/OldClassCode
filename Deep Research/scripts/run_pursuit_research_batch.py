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
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.pursuit_research_batch import (  # noqa: E402
    PursuitResearchBatchRunner,
    default_stakeholder_pursuit_accounts,
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
        help="Concurrent account runs. Default 1. Max 2 for safety.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write the account plan but do not call ProConnect or Deep Research.",
    )
    return parser.parse_args()


async def main_async() -> int:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    accounts = load_accounts_jsonl(args.accounts_jsonl) if args.accounts_jsonl else default_stakeholder_pursuit_accounts()
    output_dir = args.output_dir or (
        ROOT
        / "scripts"
        / "output"
        / "pursuit_research"
        / datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    plan_path = output_dir / "batch_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "account_count": len(accounts),
                "concurrency": max(1, min(args.concurrency, 2)),
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

    print(f"Running {len(accounts)} account(s) with concurrency={max(1, min(args.concurrency, 2))}")
    runner = PursuitResearchBatchRunner(
        output_dir=output_dir,
        concurrency=args.concurrency,
    )
    summary = await runner.run(accounts)
    print(f"Batch complete: {summary['succeeded']} succeeded, {summary['failed']} failed")
    print(f"Output directory: {summary['output_dir']}")
    print(f"Summary: {Path(summary['output_dir']) / 'batch_summary.json'}")
    return 0 if summary["failed"] == 0 else 1


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
