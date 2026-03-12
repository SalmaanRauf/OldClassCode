from __future__ import annotations

import sys
from pathlib import Path
import pytest


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from proconnect_har_inspector import resolve_har_path, summarize_har_payload  # noqa: E402


def test_summarize_har_payload_surfaces_interesting_routes_and_html_shells() -> None:
    payload = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "GET",
                        "url": "https://proconnect.protiviti.com/api/prospects?search=%27Jennifer%20Brady%27",
                        "queryString": [{"name": "search", "value": "'Jennifer Brady'"}],
                    },
                    "response": {
                        "status": 200,
                        "content": {
                            "mimeType": "application/json",
                            "text": '{"value":[{"document":{"name":"Jennifer Brady"}}]}',
                        },
                    },
                },
                {
                    "request": {
                        "method": "GET",
                        "url": "https://proconnect.protiviti.com/api/accounts/00130000000BYUIAA4",
                        "queryString": [],
                    },
                    "response": {
                        "status": 200,
                        "content": {
                            "mimeType": "application/json",
                            "text": '{"id":"00130000000BYUIAA4","name":"Fannie Mae"}',
                        },
                    },
                },
                {
                    "request": {
                        "method": "GET",
                        "url": "https://proconnect.protiviti.com/api/userHistory?accountId=00130000000BYU2AAO",
                        "queryString": [{"name": "accountId", "value": "00130000000BYU2AAO"}],
                    },
                    "response": {
                        "status": 200,
                        "content": {
                            "mimeType": "text/html",
                            "text": (
                                '<!doctype html><html lang="en"><head><meta charset="utf-8"/>'
                                '<link rel="icon" href="/proconnect-logo.png"/></head><body></body></html>'
                            ),
                        },
                    },
                },
                {
                    "request": {
                        "method": "GET",
                        "url": "https://proconnect.protiviti.com/api/people/003ABC123456789?accountId=00130000000BYU2AAO",
                        "queryString": [{"name": "accountId", "value": "00130000000BYU2AAO"}],
                    },
                    "response": {
                        "status": 200,
                        "content": {
                            "mimeType": "application/json",
                            "text": '{"id":"003ABC123456789","photoUrl":"https://img.example.com/jb.png"}',
                        },
                    },
                },
            ]
        }
    }

    summary = summarize_har_payload(payload)

    assert [route["canonical_path"] for route in summary["known_routes"]] == [
        "/api/accounts/{id}",
        "/api/prospects",
    ]
    assert [route["canonical_path"] for route in summary["interesting_routes"]] == [
        "/api/people/{id}",
        "/api/userHistory",
    ]
    assert summary["interesting_routes"][0]["response_kinds"] == ["json"]
    assert summary["interesting_routes"][1]["response_kinds"] == ["html_shell"]
    assert summary["interesting_routes"][1]["query_keys"] == ["accountId"]


def test_resolve_har_path_accepts_har_txt_sibling(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    actual_file = output_dir / "proconnect_jennifer_brady.har.txt"
    actual_file.write_text('{"log":{"entries":[]}}', encoding="utf-8")

    resolved = resolve_har_path(str(output_dir / "proconnect_jennifer_brady.har"), cwd=tmp_path)

    assert resolved == actual_file.resolve()


def test_resolve_har_path_searches_workspace_for_named_file(tmp_path: Path) -> None:
    actual_dir = tmp_path / "nested" / "artifacts"
    actual_dir.mkdir(parents=True)
    actual_file = actual_dir / "proconnect_jennifer_brady.har"
    actual_file.write_text('{"log":{"entries":[]}}', encoding="utf-8")

    resolved = resolve_har_path("proconnect_jennifer_brady.har", cwd=tmp_path)

    assert resolved == actual_file.resolve()


def test_resolve_har_path_raises_helpful_error_when_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError) as exc_info:
        resolve_har_path(str(tmp_path / "missing.har"), cwd=tmp_path)

    message = str(exc_info.value)
    assert "Could not find HAR file" in message
    assert "Looked for" in message
