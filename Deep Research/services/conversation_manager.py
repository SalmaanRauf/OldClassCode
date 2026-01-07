# services/conversation_manager.py
from __future__ import annotations
import re
import asyncio
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple
from services.session_manager import session_manager
from services.classifier import classify_topics

HISTORY_MAX_MESSAGES = 40  # rolling window to avoid memory bloat
CONTEXT_CLEANUP_INTERVAL = 300  # 5 minutes
MAX_CONTEXT_AGE = 3600  # 1 hour

class QueryType(Enum):
    NEW_ANALYSIS = auto()
    FOLLOW_UP = auto()
    CLARIFICATION = auto()
    COMPARE_COMPANIES = auto()
    GENERAL_RESEARCH = auto()
    UNKNOWN = auto()

@dataclass
class AnalysisBlob:
    """Holds a single company's analysis snapshot."""
    company_name: str
    ticker: Optional[str] = None
    gwbs_sections: Dict[str, Any] = field(default_factory=dict)
    analyst_summary: Optional[str] = None
    analyst_events: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AnalysisBlob":
        d = dict(d)
        if isinstance(d.get("timestamp"), str):
            d["timestamp"] = datetime.fromisoformat(d["timestamp"])
        return cls(**d)

@dataclass
class ConversationContext:
    """Session-scoped context and history."""
    session_id: str
    current_company: Optional[Dict[str, Optional[str]]] = None  # {"name": str, "ticker": Optional[str]}
    chat_history: List[Dict[str, str]] = field(default_factory=list)
    analyses: Dict[str, AnalysisBlob] = field(default_factory=dict)  # key = company_name.lower()
    available_companies: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed: datetime = field(default_factory=datetime.utcnow)

    # --- history management ---
    def add_message(self, role: str, content: str) -> None:
        self.chat_history.append({"role": role, "content": content})
        if len(self.chat_history) > HISTORY_MAX_MESSAGES:
            # drop from the front
            self.chat_history = self.chat_history[-HISTORY_MAX_MESSAGES:]
        self.last_accessed = datetime.utcnow()

    # --- company handling ---
    def set_company(self, name: str, ticker: Optional[str] = None) -> None:
        name = name.strip()
        self.current_company = {"name": name, "ticker": ticker}
        self.last_accessed = datetime.utcnow()

    def get_company_key(self) -> Optional[str]:
        if not self.current_company:
            return None
        return (self.current_company.get("name") or "").lower().strip() or None

    # --- analysis handling ---
    def set_analysis(self, blob: AnalysisBlob) -> None:
        key = (blob.company_name or "").lower().strip()
        if key:
            self.analyses[key] = blob
            # If first analysis or company switch, set it current
            if not self.current_company or self.get_company_key() != key:
                self.current_company = {"name": blob.company_name, "ticker": blob.ticker}
        self.last_accessed = datetime.utcnow()

    def get_analysis(self, company_name: Optional[str] = None) -> Optional[AnalysisBlob]:
        key = (company_name or (self.current_company or {}).get("name") or "").lower().strip()
        result = self.analyses.get(key) if key else None
        if result:
            self.last_accessed = datetime.utcnow()
        return result

    # --- cleanup methods ---
    def is_expired(self) -> bool:
        """Check if context is expired based on last access time."""
        return (datetime.utcnow() - self.last_accessed).total_seconds() > MAX_CONTEXT_AGE

    def cleanup_old_analyses(self, max_age_hours: int = 24) -> int:
        """Remove analyses older than max_age_hours. Returns number of analyses removed."""
        cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
        to_remove = []
        
        for key, analysis in self.analyses.items():
            if analysis.timestamp < cutoff_time:
                to_remove.append(key)
        
        for key in to_remove:
            del self.analyses[key]
        
        return len(to_remove)

    # --- (de)serialization ---
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "current_company": self.current_company,
            "chat_history": list(self.chat_history),
            "available_companies": list(self.available_companies),
            "analyses": {k: v.to_dict() for k, v in self.analyses.items()},
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ConversationContext":
        ctx = cls(
            session_id=d["session_id"],
            current_company=d.get("current_company"),
            chat_history=d.get("chat_history", []),
            available_companies=d.get("available_companies", []),
            created_at=datetime.fromisoformat(d.get("created_at", datetime.utcnow().isoformat())),
            last_accessed=datetime.fromisoformat(d.get("last_accessed", datetime.utcnow().isoformat())),
        )
        for k, v in (d.get("analyses") or {}).items():
            ctx.analyses[k] = AnalysisBlob.from_dict(v)
        return ctx

# -------- routing --------

_TICKER_RE = re.compile(r"\b([A-Z]{1,5})\b")
# naive "compare" detector: Company A vs Company B, A vs B, A versus B
_COMPARE_RE = re.compile(r"\b(.+?)\s+(?:vs|versus|compared to)\s+(.+)$", re.I)
# pronoun for continuing context
_PRONOUN_RE = re.compile(r"\b(it|this (?:company|firm)|they|them)\b", re.I)

# company-ish: words, dots, ampersands, commas, spaces; avoid trailing corporate suffix noise in routing
_COMPANY_CLEAN_RE = re.compile(r"\b(inc|inc\.|corp|corp\.|co|co\.|ltd|ltd\.|llc)\b", re.I)

def _clean_company(s: str) -> str:
    if not s:
        return ""
    
    s = s.strip()
    # Preserve tickers (all caps 1-5 letters)
    if re.fullmatch(r"[A-Z]{1,5}", s):
        return s
    
    # Allow digit-leading names like "3M"
    if re.match(r"^[0-9]", s):
        return s
    
    # Clean corporate suffixes and normalize
    s = _COMPANY_CLEAN_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" ,.")
    return s

FOLLOW_UP_HINTS = re.compile(r"\b(what|how|why|when|where|who|which|tell me more|can you explain|elaborate)\b", re.I)

class QueryRouter:
    """Deterministic, explainable router for chat input."""

    def route(self, user_text: str, ctx: ConversationContext) -> Tuple[QueryType, Dict[str, Any]]:
        q = user_text.strip()

        # A vs B?
        m = _COMPARE_RE.search(q)
        if m:
            a, b = _clean_company(m.group(1)), _clean_company(m.group(2))
            if a and b and a.lower() != b.lower():
                return QueryType.COMPARE_COMPANIES, {"companies": [a, b]}

        # Check for new analysis imperatives or "briefing/report on X" FIRST
        # 1) Natural phrasing: "briefing/report on/about/for <company>"
        m3 = re.search(r"\b(?:briefing|report)\s+(?:on|about|for)\s+(.+)$", q, re.I)
        if m3:
            comp = _clean_company(m3.group(1))
            if comp:
                return QueryType.NEW_ANALYSIS, {
                    "company": {"name": comp, "ticker": None},
                    "extra_topics": classify_topics(q)
                }

        # 2) Verb-oriented imperative
        if re.search(r"\b(analyze|research|look up|find info(?:rmation)? (?:on|about)|company report)\b", q, re.I):
            # try to pull a name chunk after the verb
            m2 = re.search(r"(?:analyze|research|look up|about|on)\s+(.+)$", q, re.I)
            if m2:
                comp = _clean_company(m2.group(1))
                if comp:
                    return QueryType.NEW_ANALYSIS, {
                        "company": {"name": comp, "ticker": None},
                        "extra_topics": classify_topics(q)
                    }
            # If no company extracted, treat as general research
            return QueryType.GENERAL_RESEARCH, {"prompt": q}

        # Try to extract an explicit company
        # Heuristic: if it's short & all caps, assume ticker; else treat as name
        tokens = [t.strip() for t in re.split(r"[,\n]", q) if t.strip()]
        if len(tokens) == 1 and len(q.split()) <= 6 and not FOLLOW_UP_HINTS.search(q):
            single = tokens[0]
            if _TICKER_RE.fullmatch(single):
                # single ticker like "COF"
                return QueryType.NEW_ANALYSIS, {
                    "company": {"name": single, "ticker": single},
                    "extra_topics": classify_topics(q)
                }
            else:
                # treat as company name (case-insensitive)
                return QueryType.NEW_ANALYSIS, {
                    "company": {"name": _clean_company(single), "ticker": None},
                    "extra_topics": classify_topics(q)
                }

        # Check for follow-up hints (after checking for new analysis)
        if FOLLOW_UP_HINTS.search(q):
            # If pronoun and we have a current company, treat as follow-up
            if _PRONOUN_RE.search(q) and ctx.current_company:
                return QueryType.FOLLOW_UP, {"company": ctx.current_company}
            # If the question seems general and we already have an analysis, follow-up
            if ctx.get_analysis() is not None:
                return QueryType.FOLLOW_UP, {"company": ctx.current_company or {}}

        # If we have an active company and the user didn't provide a clear new one, default to follow-up.
        if ctx.current_company:
            return QueryType.FOLLOW_UP, {"company": ctx.current_company}

        # If the input sounds like a general ask (contains research-y verbs), route to general research
        if re.search(r"\b(summary|summarize|context|overview|landscape|trends|recent|what's new)\b", q, re.I):
            return QueryType.GENERAL_RESEARCH, {"prompt": q}

        # Otherwise, needs clarification (e.g., "help me decide" with no company)
        return QueryType.CLARIFICATION, {}

"""Routing logic uses services.classifier.classify_topics; no local patterns here."""

class ConversationManager:
    """Main conversation management service with proper cleanup."""
    
    def __init__(self):
        self.query_router = QueryRouter()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
    
    def start_cleanup(self):
        """Start the background cleanup task."""
        if not self._running:
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    def stop_cleanup(self):
        """Stop the background cleanup task."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
    
    async def _cleanup_loop(self):
        """Background task to clean up old contexts."""
        while self._running:
            try:
                await asyncio.sleep(CONTEXT_CLEANUP_INTERVAL)
                await self._cleanup_old_contexts()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in context cleanup loop: {e}")
    
    async def _cleanup_old_contexts(self):
        """Clean up old contexts and analyses."""
        session_info = session_manager.get_session_info()
        cleaned_sessions = 0
        cleaned_analyses = 0
        
        for session_id, info in session_info.items():
            if info["idle_seconds"] > MAX_CONTEXT_AGE:
                # Remove expired session
                session_manager.remove_session(session_id)
                cleaned_sessions += 1
            else:
                # Clean up old analyses in active sessions
                session_id, context = session_manager.get_or_create_session(session_id)
                if hasattr(context, 'cleanup_old_analyses'):
                    removed = context.cleanup_old_analyses()
                    cleaned_analyses += removed
        
        if cleaned_sessions > 0 or cleaned_analyses > 0:
            print(f"Cleanup: removed {cleaned_sessions} sessions, {cleaned_analyses} old analyses")
    
    def get_or_create_context(self, session_id: str) -> ConversationContext:
        """Get existing context or create new one for session."""
        def create_context(session_id: str) -> ConversationContext:
            return ConversationContext(session_id=session_id)
        
        session_id, context = session_manager.get_or_create_session(session_id, create_context)
        return context
    
    def clear_session(self, session_id: str):
        """Clear conversation context for a session."""
        session_manager.remove_session(session_id)
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get statistics about active sessions."""
        session_info = session_manager.get_session_info()
        total_sessions = len(session_info)
        total_analyses = 0
        
        for session_id, info in session_info.items():
            session_id, context = session_manager.get_or_create_session(session_id)
            if hasattr(context, 'analyses'):
                total_analyses += len(context.analyses)
        
        return {
            "total_sessions": total_sessions,
            "total_analyses": total_analyses,
            "session_details": session_info
        }

# Global conversation manager instance
conversation_manager = ConversationManager()