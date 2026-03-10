#!/usr/bin/env python3
"""
Replay BD enrichment from a saved Deep Research payload.

This script bypasses the expensive Deep Research API call and feeds a captured
Deep Research result into the same BD enrichment pipeline used in app runs:
  Deep Research markdown -> BDOrchestrator -> Credentials Agent -> Final Analyst

Default fixture:
  scripts/fixtures/capital_one_fs_all_signals_20260218.json

Usage examples:
  python scripts/replay_bd_from_deep_research.py
  python scripts/replay_bd_from_deep_research.py --fixture scripts/fixtures/capital_one_fs_all_signals_20260218.json
  python scripts/replay_bd_from_deep_research.py --show-credentials-io --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from models.bd_schemas import MDReport
from services.bd_orchestrator import BDOrchestrator
from services.bd_report_formatter import format_bd_report_as_section
from services.bd_trigger_context import build_trigger_for_bd_enrichment
from services.deep_research_formatter import (
    build_structured_evidence_map,
    format_deep_research_response_as_markdown,
)
from services.runtime_policy import get_runtime_policy


PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_FIXTURE = PROJECT_ROOT / "scripts" / "fixtures" / "capital_one_fs_all_signals_20260218.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "scripts" / "output" / "bd_replay_runs"
DEFAULT_TRACES_DIR = PROJECT_ROOT / "traces"


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Fixture must be a JSON object: {path}")
    return data


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_urls(text: str) -> List[str]:
    raw_urls = re.findall(r"https?://[^\s\]\)>,]+", text or "")
    urls: List[str] = []
    seen = set()
    for raw in raw_urls:
        cleaned = raw.strip().rstrip(".,;)")
        if cleaned and cleaned not in seen:
            urls.append(cleaned)
            seen.add(cleaned)
    return urls


def _normalize_deep_research_markdown(text: str) -> str:
    """Strip non-DR wrappers when users paste full UI output."""
    normalized = (text or "").strip()

    if "Final Report:" in normalized:
        normalized = normalized.split("Final Report:", 1)[1].strip()

    # Remove previously-enriched BD block if present.
    if "🎯 BD Analysis & Credentials Validation" in normalized:
        normalized = normalized.split("🎯 BD Analysis & Credentials Validation", 1)[0].strip()

    # Remove trace dump if appended.
    if "\nTrace:" in normalized:
        normalized = normalized.split("\nTrace:", 1)[0].strip()

    return normalized


def _append_sources_if_missing(markdown: str, source_urls: List[str]) -> str:
    if not source_urls:
        return markdown
    existing = set(_extract_urls(markdown))
    missing = [url for url in source_urls if url and url not in existing]
    if not missing:
        return markdown
    lines = [markdown.rstrip(), "", "## Sources"]
    lines.extend(f"• {url}" for url in missing)
    lines.append("")
    return "\n".join(lines)


def _model_dump(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        try:
            return model.model_dump(mode="json")
        except TypeError:
            return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    raise TypeError(f"Unsupported model type: {type(model)}")


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _resolve_fixture_payload(fixture: Dict[str, Any], fixture_path: Path) -> Tuple[str, List[str]]:
    response_obj = fixture.get("deep_research_response")
    if isinstance(response_obj, dict):
        markdown = format_deep_research_response_as_markdown(response_obj)
    else:
        markdown = ""

    if not markdown:
        markdown = str(fixture.get("deep_research_markdown", "")).strip()
    markdown_path_value = str(fixture.get("deep_research_markdown_path", "")).strip()
    if not markdown and markdown_path_value:
        markdown_path = Path(markdown_path_value)
        if not markdown_path.is_absolute():
            markdown_path = fixture_path.parent / markdown_path
        markdown = _read_text(markdown_path)
    if not markdown:
        raise ValueError("Fixture must include deep_research_markdown or deep_research_markdown_path")

    source_urls_raw = fixture.get("source_urls", [])
    source_urls = [str(item).strip() for item in source_urls_raw if str(item).strip()]
    return markdown, source_urls


def _coerce_deep_research_response(
    fixture: Dict[str, Any],
    markdown: str,
    source_urls: List[str],
) -> Dict[str, Any]:
    response_obj = fixture.get("deep_research_response")
    if isinstance(response_obj, dict):
        return response_obj

    citations = [{"title": url, "url": url} for url in source_urls]
    return {
        "summary": "",
        "sections": [
            {
                "title": "Final Report",
                "content": markdown,
            }
        ],
        "citations": citations,
    }


def _extract_response_source_urls(response: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    seen = set()

    def _add(url: Any) -> None:
        value = str(url or "").strip()
        if not value.startswith(("http://", "https://")):
            return
        key = value.lower()
        if key in seen:
            return
        seen.add(key)
        urls.append(value)

    for citation in response.get("citations", []) or []:
        if isinstance(citation, dict):
            _add(citation.get("url"))

    for section in response.get("sections", []) or []:
        if not isinstance(section, dict):
            continue
        for citation in section.get("citations", []) or []:
            if isinstance(citation, dict):
                _add(citation.get("url"))

    metadata = response.get("metadata", {}) or {}
    for key in ("discovery_sources", "confirmation_sources", "display_sources"):
        for url in metadata.get(key, []) or []:
            _add(url)

    return urls


def _build_run_query(
    fixture: Dict[str, Any],
    company: str,
    geography: str,
    signals: str,
    time_window_days: int,
) -> str:
    fixture_query = str(fixture.get("user_query", "")).strip()
    if fixture_query:
        return fixture_query
    return (
        f"Research Financial Services sector developments related to {company}, "
        f"capturing {signals} signals. Focus on activity within {geography} "
        f"over the past {time_window_days} days."
    )


def _build_session_params(
    fixture: Dict[str, Any],
    company: str,
    geography: str,
    signals: str,
    time_window_days: int,
) -> Dict[str, Any]:
    params = fixture.get("session_params", {})
    if not isinstance(params, dict):
        params = {}
    merged: Dict[str, Any] = dict(params)
    merged["company"] = company
    merged["geography"] = geography
    merged["signals"] = signals
    merged["time_window"] = f"{time_window_days} days"
    return merged


def _print_report_summary(report: MDReport) -> None:
    policy = get_runtime_policy()
    print("\n=== Replay Summary ===")
    print(f"- opportunity_extraction_status: {report.opportunity_extraction_status}")
    print(f"- opportunities_extracted_count: {report.opportunities_extracted_count}")
    print(f"- lookups_executed_count: {report.lookups_executed_count}")
    matched = report.credentials_status_counts.get("Matched", 0)
    no_match = report.credentials_status_counts.get("No Match", 0)
    if policy.show_failures:
        failed = report.credentials_status_counts.get("Lookup Failed", 0)
        print(f"- credentials_status_counts: matched={matched}, no_match={no_match}, failed={failed}")
    else:
        print(f"- credentials_status_counts: matched={matched}, no_match={no_match}")
    print(f"- synthesis_status: {report.synthesis_status}")
    if report.synthesis_fallback_reason:
        print(f"- synthesis_fallback_reason: {report.synthesis_fallback_reason}")

    if report.phase2_signal_evidence:
        print("\nPhase 2 signals:")
        for item in report.phase2_signal_evidence:
            print(f"  - {item.signal_code}: {item.status}")

    if report.top_opportunities:
        print("\nTop opportunities:")
        for idx, opp in enumerate(report.top_opportunities, 1):
            print(
                f"  {idx}. {opp.opportunity.title} | validation={opp.validation_status} "
                f"| lookup={opp.credentials_lookup_status} | credentials={len(opp.credentials)}"
            )


def _print_credentials_io(report: MDReport) -> None:
    if not report.credentials_evidence:
        print("\n(no credentials I/O records available)")
        return
    print("\n=== Credentials I/O ===")
    for idx, diag in enumerate(report.credentials_evidence, 1):
        print(f"\n[{idx}] {diag.opportunity_title}")
        print(f"status={diag.lookup_status} parse_outcome={diag.parse_outcome} matches={diag.match_count}")
        print("query_text:")
        print(diag.query_text or "(empty)")
        print("raw_response_text:")
        print(diag.raw_response_text or "(empty)")


async def _run(args: argparse.Namespace) -> int:
    load_dotenv()

    fixture_path = Path(args.fixture).expanduser().resolve()
    fixture = _load_json(fixture_path)

    sector = str(args.sector or fixture.get("sector", "financial_services")).strip()
    company = str(args.company or fixture.get("company", "Capital One")).strip()
    geography = str(args.geography or fixture.get("geography", "CONUS")).strip()
    signals = str(args.signals or fixture.get("signals", "All")).strip()
    time_window_days = int(args.time_window_days or fixture.get("time_window_days", 180))

    deep_markdown, source_urls = _resolve_fixture_payload(fixture, fixture_path)
    deep_markdown = _normalize_deep_research_markdown(deep_markdown)
    deep_markdown = _append_sources_if_missing(deep_markdown, source_urls)
    deep_research_response_obj = _coerce_deep_research_response(fixture, deep_markdown, source_urls)
    structured_source_urls = _extract_response_source_urls(deep_research_response_obj)
    structured_evidence_map = build_structured_evidence_map(deep_research_response_obj)

    user_query = str(args.user_query).strip() if args.user_query else _build_run_query(
        fixture,
        company=company,
        geography=geography,
        signals=signals,
        time_window_days=time_window_days,
    )
    session_params = _build_session_params(
        fixture,
        company=company,
        geography=geography,
        signals=signals,
        time_window_days=time_window_days,
    )

    trigger = build_trigger_for_bd_enrichment(
        sector=sector,
        user_query=user_query,
        session_params=session_params,
    )

    print("\n=== Replay Input ===")
    print(f"fixture={fixture_path}")
    print(f"sector={sector}")
    print(f"company={company}")
    print(f"geography={geography}")
    print(f"requested_signals={signals}")
    print(f"trigger_signals={trigger.signals}")
    print(f"deep_research_chars={len(deep_markdown)}")
    print(f"deep_research_urls={len(_extract_urls(deep_markdown))}")

    traces_dir = Path(args.traces_dir).expanduser().resolve() if args.traces_dir else DEFAULT_TRACES_DIR

    async def progress(msg: str) -> None:
        if args.verbose:
            print(f"[progress] {msg}")

    orchestrator = BDOrchestrator(
        traces_dir=traces_dir,
        use_atlas_digestion=not args.disable_atlas_digestion,
        credentials_lookup_mode=args.credentials_lookup_mode,
    )

    report = await orchestrator.run(
        trigger=trigger,
        deep_research_output=deep_markdown,
        structured_source_urls=structured_source_urls,
        structured_evidence_map=structured_evidence_map,
        progress_cb=progress if args.verbose else None,
    )

    _print_report_summary(report)
    if args.show_credentials_io:
        _print_credentials_io(report)

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    deep_hash = hashlib.sha256(deep_markdown.encode("utf-8")).hexdigest()[:12]
    stem = f"bd_replay_{ts}_{deep_hash}"

    report_dict = _model_dump(report)
    section = format_bd_report_as_section(report)
    section_content = section.get("content", "") if section else ""

    payload = {
        "timestamp_utc": ts,
        "fixture_path": str(fixture_path),
        "user_query": user_query,
        "session_params": session_params,
        "trigger": _model_dump(trigger),
        "deep_research_markdown_chars": len(deep_markdown),
        "deep_research_markdown_sha256": hashlib.sha256(deep_markdown.encode("utf-8")).hexdigest(),
        "deep_research_response": deep_research_response_obj,
        "report": report_dict,
        "bd_section": section,
    }

    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    md_path.write_text(section_content, encoding="utf-8")

    print("\n=== Artifacts ===")
    print(f"- JSON: {json_path}")
    print(f"- Markdown: {md_path}")
    print("\nReplay complete.")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay BD enrichment using a saved Deep Research payload."
    )
    parser.add_argument(
        "--fixture",
        default=str(DEFAULT_FIXTURE),
        help="Path to replay fixture JSON.",
    )
    parser.add_argument("--sector", default=None, help="Sector override (default from fixture).")
    parser.add_argument("--company", default=None, help="Company override (default from fixture).")
    parser.add_argument("--geography", default=None, help="Geography override (default from fixture).")
    parser.add_argument("--signals", default=None, help="Signals override (e.g., All, Executive Movement).")
    parser.add_argument("--time-window-days", type=int, default=None, help="Lookback window override.")
    parser.add_argument("--user-query", default=None, help="Optional user query override.")
    parser.add_argument(
        "--credentials-lookup-mode",
        choices=["serial_per_opportunity", "batched_single_call"],
        default="serial_per_opportunity",
        help="Credentials lookup mode.",
    )
    parser.add_argument(
        "--disable-atlas-digestion",
        action="store_true",
        help="Disable ATLAS opportunity digest stage in orchestrator.",
    )
    parser.add_argument(
        "--show-credentials-io",
        action="store_true",
        help="Print full credentials query and raw response text to stdout.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for replay artifacts (JSON + markdown).",
    )
    parser.add_argument(
        "--traces-dir",
        default=str(DEFAULT_TRACES_DIR),
        help="Directory where BDOrchestrator trace files are written.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print pipeline progress updates.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:
        print(f"\nReplay failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
