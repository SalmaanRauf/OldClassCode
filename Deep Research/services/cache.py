"""
Simple TTL cache utilities for tool calls.
"""
from __future__ import annotations
import time
import threading
from typing import Any, Optional, Tuple
import json
import hashlib


class TTLCache:
    def __init__(self, maxsize: int = 256, ttl_seconds: int = 1800):
        self._data: dict[str, Tuple[float, Any]] = {}
        self._lock = threading.RLock()
        self._ttl = ttl_seconds
        self._max = maxsize

    def _evict_if_needed(self) -> None:
        if len(self._data) <= self._max:
            return
        items = sorted(self._data.items(), key=lambda kv: kv[1][0])
        for k, _ in items[: max(1, len(items) - self._max)]:
            self._data.pop(k, None)

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        with self._lock:
            v = self._data.get(key)
            if not v:
                return None
            ts, payload = v
            if now - ts > self._ttl:
                self._data.pop(key, None)
                return None
            return payload

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.time(), value)
            self._evict_if_needed()


def cache_key(*parts: Any) -> str:
    """
    Build a robust, collision-resistant cache key from arbitrary parts.

    Rationale:
    - Avoid naïve string joins that can collide (e.g., when parts contain separators).
    - Preserve semantic identity by normalizing structured values.
    - Produce a stable key suitable for dictionary indexing.

    Strategy:
    - Normalize each part into a JSON-serializable value (dict/vars/str fallbacks).
    - Serialize the list of normalized parts to compact JSON and hash it (SHA1).
    - Append a short human-readable suffix for quick inspection in logs.
    """
    def _normalize(v: Any) -> Any:
        if v is None or isinstance(v, (str, int, float, bool)):
            return v
        # Best-effort conversion for Pydantic/BaseModel or dataclasses
        for attr in ("dict", "model_dump"):
            try:
                m = getattr(v, attr)
                if callable(m):
                    return m()
            except Exception:
                pass
        try:
            return vars(v)
        except Exception:
            return str(v)

    normalized = [_normalize(p) for p in parts]
    raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    # Compact human-readable suffix (best-effort)
    preview = []
    for p in parts:
        s = ("null" if p is None else str(p)).strip().lower()
        preview.append(s[:16])
    suffix = "|".join(preview)
    return f"ck:{digest}:{suffix}"