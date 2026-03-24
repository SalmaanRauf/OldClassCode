"""
Runtime-safe ProConnect authentication helpers.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple


def resolve_runtime_bearer_token(
    *,
    cli_token: Optional[str] = None,
    token_file: Optional[str] = None,
    fallback_paths: Optional[list[str | Path]] = None,
) -> Tuple[str, str]:
    """Resolve a ProConnect bearer token without interactive prompts."""
    if cli_token and str(cli_token).strip():
        return _normalize_token(str(cli_token).strip()), "cli"

    env_token = str(os.getenv("PROCONNECT_BEARER_TOKEN") or "").strip()
    if env_token:
        return _normalize_token(env_token), "env:PROCONNECT_BEARER_TOKEN"

    search_paths: list[Path] = []
    if token_file:
        search_paths.append(Path(token_file).expanduser())
    for path in fallback_paths or []:
        search_paths.append(Path(path).expanduser())

    seen: set[str] = set()
    for path in search_paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return _normalize_token(text), f"file:{path}"

    if token_file:
        raise FileNotFoundError(f"ProConnect token file not found or empty: {token_file}")
    raise RuntimeError(
        "ProConnect credentials are not configured. Set PROCONNECT_BEARER_TOKEN or PROCONNECT_TOKEN_FILE."
    )


def _normalize_token(token: str) -> str:
    normalized = token.strip()
    if not normalized.lower().startswith("bearer "):
        normalized = f"Bearer {normalized}"
    return normalized
