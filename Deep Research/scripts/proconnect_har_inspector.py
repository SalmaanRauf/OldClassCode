#!/usr/bin/env python3
"""Summarize ProConnect HAR files to discover real API routes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import parse_qsl, urlparse


KNOWN_PROCONNECT_ROUTES = {
    "/api/prospects",
    "/api/accounts/{id}",
    "/api/orgchart",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--har", required=True, help="Path to exported HAR file.")
    return parser.parse_args()


def load_har_payload(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("HAR root must be a JSON object.")
    return payload


def summarize_har_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    entries = to_list(payload.get("log", {}).get("entries"))
    route_summaries = collect_route_summaries(entries)
    known_routes = [
        route for route in route_summaries if route["canonical_path"].lower() in KNOWN_PROCONNECT_ROUTES
    ]
    interesting_routes = [
        route for route in route_summaries if route["canonical_path"].lower() not in KNOWN_PROCONNECT_ROUTES
    ]
    html_shell_routes = [
        route for route in route_summaries if "html_shell" in route.get("response_kinds", [])
    ]
    return {
        "entry_count": len(entries),
        "route_count": len(route_summaries),
        "known_routes": known_routes,
        "interesting_routes": interesting_routes,
        "html_shell_routes": html_shell_routes,
    }


def collect_route_summaries(entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for entry in entries:
        request = entry.get("request") if isinstance(entry.get("request"), dict) else {}
        response = entry.get("response") if isinstance(entry.get("response"), dict) else {}

        method = str(request.get("method") or "GET").upper()
        url = str(request.get("url") or "")
        if not url:
            continue

        parsed = urlparse(url)
        if not parsed.path.lower().startswith("/api/"):
            continue

        canonical_path = canonicalize_api_path(parsed.path)
        response_kind = classify_har_response(response)
        content = response.get("content") if isinstance(response.get("content"), dict) else {}
        mime_type = str(content.get("mimeType") or "")

        query_keys = extract_query_keys(request, parsed.query)
        group_key = (method, canonical_path)
        summary = grouped.setdefault(
            group_key,
            {
                "method": method,
                "canonical_path": canonical_path,
                "count": 0,
                "statuses": set(),
                "response_kinds": set(),
                "content_types": set(),
                "query_keys": set(),
                "sample_url": url,
            },
        )
        summary["count"] += 1
        if response.get("status") is not None:
            summary["statuses"].add(int(response.get("status")))
        if response_kind:
            summary["response_kinds"].add(response_kind)
        if mime_type:
            summary["content_types"].add(mime_type)
        summary["query_keys"].update(query_keys)

    results: List[Dict[str, Any]] = []
    for summary in grouped.values():
        results.append(
            {
                "method": summary["method"],
                "canonical_path": summary["canonical_path"],
                "count": summary["count"],
                "statuses": sorted(summary["statuses"]),
                "response_kinds": sorted(summary["response_kinds"]),
                "content_types": sorted(summary["content_types"]),
                "query_keys": sorted(summary["query_keys"]),
                "sample_url": summary["sample_url"],
            }
        )
    results.sort(key=lambda item: (item["canonical_path"].lower(), item["method"]))
    return results


def canonicalize_api_path(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    canonical_parts: List[str] = []
    for part in parts:
        canonical_parts.append(canonicalize_path_segment(part))
    return "/" + "/".join(canonical_parts)


def canonicalize_path_segment(part: str) -> str:
    if looks_like_identifier(part):
        return "{id}"
    return part


def looks_like_identifier(part: str) -> bool:
    if not part:
        return False
    if len(part) >= 15 and part.isalnum() and any(char.isdigit() for char in part):
        return True
    if len(part) >= 8 and part.replace("-", "").isalnum() and part.count("-") >= 2:
        return True
    if part.isdigit() and len(part) >= 6:
        return True
    return False


def extract_query_keys(request: Dict[str, Any], parsed_query: str) -> List[str]:
    query_items = request.get("queryString")
    if isinstance(query_items, list) and query_items:
        keys = [str(item.get("name")) for item in query_items if isinstance(item, dict) and item.get("name")]
        if keys:
            return keys
    return [key for key, _ in parse_qsl(parsed_query, keep_blank_values=True)]


def classify_har_response(response: Dict[str, Any]) -> str:
    content = response.get("content") if isinstance(response.get("content"), dict) else {}
    text = content.get("text")
    mime_type = str(content.get("mimeType") or "").lower()

    if isinstance(text, str):
        stripped = text.strip()
        if not stripped:
            return "empty"
        if is_proconnect_html_shell_text(stripped):
            return "html_shell"
        if stripped.lower().startswith("<!doctype html") or stripped.lower().startswith("<html"):
            return "html"
        try:
            json.loads(stripped)
            return "json"
        except Exception:
            pass
        if "json" in mime_type:
            return "json"
        return "text"

    if "json" in mime_type:
        return "json"
    if "html" in mime_type:
        return "html"
    return "unknown"


def is_proconnect_html_shell_text(value: str) -> bool:
    text = value.strip().lower()
    if not text:
        return False
    if not ("<!doctype html" in text or text.startswith("<html")):
        return False
    return "proconnect-logo.png" in text or "name=\"theme-color\"" in text or "id=\"root\"" in text


def to_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def format_rows(rows: List[Dict[str, Any]]) -> List[str]:
    if not rows:
        return ["(none)"]

    rendered = []
    for row in rows:
        rendered.append(
            " | ".join(
                [
                    row["method"],
                    row["canonical_path"],
                    f"count={row['count']}",
                    f"statuses={','.join(str(item) for item in row['statuses']) or '-'}",
                    f"kinds={','.join(row['response_kinds']) or '-'}",
                    f"query={','.join(row['query_keys']) or '-'}",
                ]
            )
        )
    return rendered


def main() -> int:
    args = parse_args()
    payload = load_har_payload(args.har)
    summary = summarize_har_payload(payload)

    print("ProConnect HAR Inspector")
    print("========================")
    print(f"FILE: {Path(args.har).name}")
    print(f"ENTRIES: {summary['entry_count']}")
    print(f"UNIQUE_API_ROUTES: {summary['route_count']}")
    print("\nKNOWN ROUTES:")
    for line in format_rows(summary["known_routes"]):
        print(line)
    print("\nINTERESTING ROUTES:")
    for line in format_rows(summary["interesting_routes"]):
        print(line)
    print("\nHTML SHELL ROUTES:")
    for line in format_rows(summary["html_shell_routes"]):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
