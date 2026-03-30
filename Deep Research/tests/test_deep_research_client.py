"""
Unit tests for DeepResearchClient citation extraction fallbacks.
"""
from types import SimpleNamespace

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.deep_research_client import (
    DEEP_RESEARCH_POLL_INTERVAL_SECONDS,
    DEEP_RESEARCH_ENABLE_LIVE_PROGRESS_POLLING,
    DeepResearchClient,
    DeepResearchCitation,
    DeepResearchReport,
)


def _client() -> DeepResearchClient:
    # Bypass __init__ because these tests only exercise pure parsing helpers.
    return DeepResearchClient.__new__(DeepResearchClient)


def _text_block(value: str, annotations=None, name: str = ""):
    return SimpleNamespace(
        type="text",
        name=name,
        text=SimpleNamespace(value=value, annotations=annotations or []),
    )


def _url_annotation(url: str, title: str = ""):
    return SimpleNamespace(
        url_citation=SimpleNamespace(url=url, title=title or url),
    )


def _nested_citations_annotation(*items):
    citations = [SimpleNamespace(title=title, url=url) for title, url in items]
    return SimpleNamespace(citations=citations)


def test_parse_message_captures_plain_text_urls_when_annotations_missing():
    client = _client()
    message = SimpleNamespace(
        content=[
            _text_block(
                "Summary includes https://example.com/source-a and supporting context.",
                annotations=[],
            )
        ],
        url_citation_annotations=[],
        text="",
    )

    report = client._parse_message(message)

    urls = {citation.url for citation in report.citations}
    assert "https://example.com/source-a" in urls


def test_parse_message_dedupes_mixed_annotation_and_plain_text_urls():
    client = _client()
    duplicate_url = "https://example.com/source-a"
    unique_url = "https://example.com/source-b"
    message = SimpleNamespace(
        content=[
            _text_block(
                f"Summary includes {duplicate_url} and {unique_url}.",
                annotations=[_url_annotation(duplicate_url, "Source A")],
            )
        ],
        url_citation_annotations=[
            _url_annotation(duplicate_url, "Source A"),
        ],
        text="",
    )

    report = client._parse_message(message)

    urls = [citation.url for citation in report.citations]
    assert urls.count(duplicate_url) == 1
    assert urls.count(unique_url) == 1
    assert len(urls) == 2


def test_merge_streamed_citations_adds_urls_not_in_final_message():
    client = _client()
    report = DeepResearchReport(
        summary="summary",
        sections=[],
        citations=[DeepResearchCitation(title="A", url="https://example.com/a")],
        metadata={},
    )

    merged = client._merge_streamed_citations(
        report=report,
        streamed_urls={"https://example.com/a", "https://example.com/b"},
    )

    urls = {citation.url for citation in merged.citations}
    assert "https://example.com/a" in urls
    assert "https://example.com/b" in urls
    assert len(urls) == 2


def test_merge_streamed_citations_filters_bing_search_wrapper_urls():
    client = _client()
    report = DeepResearchReport(
        summary="summary",
        sections=[],
        citations=[],
        metadata={},
    )

    merged = client._merge_streamed_citations(
        report=report,
        streamed_urls={
            "https://www.bing.com/search?q=capital+one+people+moves",
            "https://fintechmagazine.com/news/people-move-natalie-hyche-kelly",
        },
    )

    urls = {citation.url for citation in merged.citations}
    assert "https://www.bing.com/search?q=capital+one+people+moves" not in urls
    assert "https://fintechmagazine.com/news/people-move-natalie-hyche-kelly" in urls


def test_dedupe_citations_populates_origin_type():
    client = _client()
    citations = [
        DeepResearchCitation(
            title="SEC source",
            url="https://www.sec.gov/Archives/edgar/data/123/abc.htm",
        ),
        DeepResearchCitation(
            title="Issuer source",
            url="https://investor.examplebank.com/news-release",
        ),
        DeepResearchCitation(
            title="Media source",
            url="https://www.reuters.com/world/us/example-story/",
        ),
        DeepResearchCitation(
            title="Social source",
            url="https://www.linkedin.com/posts/example_exec_post",
        ),
    ]

    deduped = client._dedupe_citations(citations)
    origin_by_url = {item.url: item.origin_type for item in deduped}

    assert origin_by_url["https://www.sec.gov/Archives/edgar/data/123/abc.htm"] == "regulatory"
    assert origin_by_url["https://investor.examplebank.com/news-release"] == "issuer"
    assert origin_by_url["https://www.reuters.com/world/us/example-story/"] == "media"
    assert origin_by_url["https://www.linkedin.com/posts/example_exec_post"] == "social"


def test_extract_citations_from_message_supports_nested_annotation_shape():
    client = _client()
    message = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text=SimpleNamespace(
                    value="text",
                    annotations=[
                        _nested_citations_annotation(
                            ("Nested A", "https://example.com/nested-a"),
                            ("Nested B", "https://www.bing.com/search?q=capital+one+people+moves"),
                        )
                    ],
                ),
            )
        ],
        url_citation_annotations=[],
    )

    urls = client._extract_citations_from_message(message)
    assert "https://example.com/nested-a" in urls
    assert "https://www.bing.com/search?q=capital+one+people+moves" in urls


def test_normalize_source_urls_can_keep_wrappers_for_discovery_and_hide_for_display():
    client = _client()
    raw = [
        "https://www.bing.com/search?q=capital+one+people+moves",
        "https://fintechmagazine.com/news/people-move-natalie-hyche-kelly",
        "https://fintechmagazine.com/news/people-move-natalie-hyche-kelly",
    ]

    discovery = client._normalize_source_urls(raw, include_search_wrappers=True)
    display = client._normalize_source_urls(raw, include_search_wrappers=False)

    assert "https://www.bing.com/search?q=capital+one+people+moves" in discovery
    assert "https://www.bing.com/search?q=capital+one+people+moves" not in display
    assert "https://fintechmagazine.com/news/people-move-natalie-hyche-kelly" in display


def test_canonicalize_url_removes_tracking_query_parameters():
    client = _client()
    canonical = client._canonicalize_url(
        "https://example.com/path?utm_source=foo&id=123&fbclid=abc"
    )

    assert canonical == "https://example.com/path?id=123"


def test_build_source_provenance_counts():
    client = _client()
    counts = client._build_source_provenance_counts(
        [
            DeepResearchCitation(title="a", url="https://sec.gov/a", origin_type="regulatory"),
            DeepResearchCitation(title="b", url="https://issuer.example.com/b", origin_type="issuer"),
            DeepResearchCitation(title="c", url="https://linkedin.com/c", origin_type="social"),
            DeepResearchCitation(title="d", url="https://media.example.com/d", origin_type="media"),
        ]
    )

    assert counts["regulatory"] == 1
    assert counts["issuer"] == 1
    assert counts["social"] == 1
    assert counts["media"] == 1


def test_build_run_query_adds_dynamic_fs_exec_policy():
    client = _client()
    client._industry = "financial_services"
    query = (
        "Research Financial Services sector opportunities for Capital One focusing on "
        "executive transition and regulatory deadline signals within CONUS over the past 180 days."
    )

    run_query = client._build_run_query(query)

    assert "Execution Policy (signal-scoped):" in run_query
    assert "Keep findings anchored to Capital One" in run_query
    assert "Executive transition:" in run_query
    assert "Regulatory deadlines:" in run_query
    assert "FinTech Magazine People Moves" in run_query


def test_build_run_query_skips_people_move_stack_when_exec_transition_not_requested():
    client = _client()
    client._industry = "financial_services"
    query = (
        "Research Financial Services sector opportunities for Capital One focusing on "
        "stress test and CECL signals within CONUS over the past 180 days."
    )

    run_query = client._build_run_query(query)

    assert "Execution Policy (signal-scoped):" in run_query
    assert "Stress test:" in run_query
    assert "CECL:" in run_query
    assert "FinTech Magazine People Moves" not in run_query


def test_collect_agent_citations_sweeps_all_assistant_messages():
    client = _client()
    first = SimpleNamespace(
        role="assistant",
        content=[
            SimpleNamespace(
                type="text",
                text=SimpleNamespace(
                    value="x",
                    annotations=[_url_annotation("https://example.com/first", "First")],
                ),
            )
        ],
        url_citation_annotations=[],
    )
    second = SimpleNamespace(
        role="assistant",
        content=[
            SimpleNamespace(
                type="text",
                text=SimpleNamespace(
                    value="y",
                    annotations=[_url_annotation("https://example.com/second", "Second")],
                ),
            )
        ],
        url_citation_annotations=[],
    )
    user_msg = SimpleNamespace(
        role="user",
        content=[],
        url_citation_annotations=[],
    )

    citations = client._collect_agent_citations([first, user_msg, second])
    assert "https://example.com/first" in citations
    assert "https://example.com/second" in citations
    assert len(citations) == 2


def test_build_run_query_keeps_prompt_budget_reasonable():
    client = _client()
    client._industry = "financial_services"
    query = (
        "Research Financial Services sector opportunities for Capital One focusing on all relevant signals "
        "across CONUS over the past 180 days."
    )
    run_query = client._build_run_query(query)

    assert len(run_query) < 5000


def test_default_poll_interval_is_40_seconds():
    assert DEEP_RESEARCH_POLL_INTERVAL_SECONDS == 40.0


def test_live_progress_polling_is_disabled_by_default():
    assert DEEP_RESEARCH_ENABLE_LIVE_PROGRESS_POLLING is False


class _AsyncItems:
    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        self._iter = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _FakeThreadsAPI:
    def __init__(self):
        self.count = 0

    async def create(self):
        self.count += 1
        return SimpleNamespace(id=f"thread-{self.count}")


class _FakeMessagesAPI:
    def __init__(self, responses_by_thread, fail_live_poll_threads=None):
        self._responses_by_thread = responses_by_thread
        self._fail_live_poll_threads = set(fail_live_poll_threads or [])
        self.created = []

    async def create(self, *, thread_id, role, content):
        self.created.append({"thread_id": thread_id, "role": role, "content": content})

    def list(self, *, thread_id, order="asc", limit=None):
        del limit
        if order == "asc" and thread_id in self._fail_live_poll_threads:
            raise RuntimeError("message polling failed")
        return _AsyncItems(self._responses_by_thread.get((thread_id, order), []))


class _FakeRunsAPI:
    def __init__(self, statuses_by_run):
        self._statuses_by_run = {
            key: list(value)
            for key, value in statuses_by_run.items()
        }
        self.created_runs = []

    async def create(self, *, thread_id, agent_id):
        del agent_id
        run_id = f"run-{len(self.created_runs) + 1}"
        run = self._statuses_by_run[run_id].pop(0)
        self.created_runs.append({"thread_id": thread_id, "run_id": run_id})
        return SimpleNamespace(**vars(run))

    async def get(self, *, thread_id, run_id):
        del thread_id
        queue = self._statuses_by_run[run_id]
        if queue:
            run = queue.pop(0)
            return SimpleNamespace(**vars(run))
        return SimpleNamespace(id=run_id, status="completed", last_error=None)

    def list_steps(self, *, thread_id, run_id):
        del thread_id, run_id
        return _AsyncItems([])


def _run_status(run_id: str, status: str, last_error=None):
    return SimpleNamespace(id=run_id, status=status, last_error=last_error)


def _assistant_message(msg_id: str, text: str):
    return SimpleNamespace(
        id=msg_id,
        role="assistant",
        content=[_text_block(text, annotations=[_url_annotation("https://example.com/source", "Source")])],
        url_citation_annotations=[],
        metadata={},
    )


@pytest.mark.asyncio
async def test_run_retries_retryable_streaming_failure_once_and_succeeds(monkeypatch):
    client = _client()
    client._industry = "financial_services"
    client._instructions_override = None
    client._agent_id = "agent-1"
    client._runtime_policy = SimpleNamespace(source_policy_mode="balanced")
    client._build_run_query = lambda query: query

    async def _ensure_client():
        return None

    client._ensure_client = _ensure_client

    sleep_calls = []

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr("services.deep_research_client.asyncio.sleep", _fake_sleep)

    retryable_error = {
        "code": "tool_server_error",
        "message": "Error: deep_research_server_error; Error in streaming messages from deep research resource: ",
    }
    responses_by_thread = {
        ("thread-1", "asc"): [],
        ("thread-1", "desc"): [],
        ("thread-2", "desc"): [_assistant_message("msg-2", "Recovered summary")],
    }
    client._client = SimpleNamespace(
        agents=SimpleNamespace(
            threads=_FakeThreadsAPI(),
            messages=_FakeMessagesAPI(responses_by_thread),
            runs=_FakeRunsAPI(
                {
                    "run-1": [
                        _run_status("run-1", "queued"),
                        _run_status("run-1", "failed", retryable_error),
                    ],
                    "run-2": [
                        _run_status("run-2", "queued"),
                        _run_status("run-2", "completed"),
                    ],
                }
            ),
        )
    )

    report = await client.run("Research Fannie Mae")

    assert report.summary == "Recovered summary"
    assert report.metadata["run_id"] == "run-2"
    assert len(client._client.agents.runs.created_runs) == 2
    assert sleep_calls


@pytest.mark.asyncio
async def test_run_refreshes_status_even_when_live_message_polling_errors(monkeypatch):
    monkeypatch.setattr("services.deep_research_client.DEEP_RESEARCH_ENABLE_LIVE_PROGRESS_POLLING", True)

    client = _client()
    client._industry = "financial_services"
    client._instructions_override = None
    client._agent_id = "agent-1"
    client._runtime_policy = SimpleNamespace(source_policy_mode="balanced")
    client._build_run_query = lambda query: query

    async def _ensure_client():
        return None

    client._ensure_client = _ensure_client

    async def _fake_sleep(seconds):
        del seconds

    monkeypatch.setattr("services.deep_research_client.asyncio.sleep", _fake_sleep)

    responses_by_thread = {
        ("thread-1", "desc"): [_assistant_message("msg-1", "Completed despite poll failure")],
    }
    client._client = SimpleNamespace(
        agents=SimpleNamespace(
            threads=_FakeThreadsAPI(),
            messages=_FakeMessagesAPI(responses_by_thread, fail_live_poll_threads={"thread-1"}),
            runs=_FakeRunsAPI(
                {
                    "run-1": [
                        _run_status("run-1", "queued"),
                        _run_status("run-1", "completed"),
                    ],
                }
            ),
        )
    )

    report = await client.run("Research Fannie Mae")

    assert report.summary == "Completed despite poll failure"
    assert report.metadata["run_id"] == "run-1"
