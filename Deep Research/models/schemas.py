"""
Pydantic models for tool inputs/outputs used by the tool-centric orchestrator.
"""
from typing import Dict, List, Optional, Literal

try:
    from pydantic import BaseModel, Field, AnyHttpUrl, validator
except Exception:  # pragma: no cover
    class BaseModel:  # type: ignore
        pass
    def Field(*args, **kwargs):  # type: ignore
        return None
    AnyHttpUrl = str  # type: ignore
    def validator(*args, **kwargs):  # type: ignore
        def _decorator(f):
            return f
        return _decorator


class CompanyRef(BaseModel):
    name: str = Field(...)
    ticker: Optional[str] = Field(None)
    @validator("name")
    def _strip(cls, v: str) -> str:  # type: ignore
        return (v or "").strip()


class Citation(BaseModel):
    title: Optional[str] = Field(None)
    url: AnyHttpUrl


ScopeLiteral = Literal[
    "sec_filings", "news", "procurement", "earnings", "industry_context", "competitors"
]


class GWBSSection(BaseModel):
    scope: ScopeLiteral
    summary: str = Field("")
    citations: List[Citation] = Field(default_factory=list)
    audit: Dict = Field(default_factory=dict)


class FullGWBS(BaseModel):
    company: CompanyRef
    sections: Dict[str, GWBSSection] = Field(default_factory=dict)


class AnalysisItem(BaseModel):
    company: str
    title: str
    content: str
    citations: List[Citation] = Field(default_factory=list)
    raw: Dict = Field(default_factory=dict)


class AnalysisEvent(BaseModel):
    title: str
    insights: Dict = Field(default_factory=dict)
    citations: List[Citation] = Field(default_factory=list)
    meta: Dict = Field(default_factory=dict)


class Briefing(BaseModel):
    company: CompanyRef
    events: List[AnalysisEvent] = Field(default_factory=list)
    summary: str = Field("")
    sections: Dict[str, str] = Field(default_factory=dict)
    # Optional: include full GWBS sections (with citations) for rich presentation
    gwbs: Dict[str, GWBSSection] = Field(default_factory=dict)