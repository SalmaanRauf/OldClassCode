#!/usr/bin/env python3
"""Shared ProConnect client and local test utilities (stdlib only)."""

from __future__ import annotations

import base64
import getpass
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://proconnect.protiviti.com"
DEFAULT_TIMEOUT_SECONDS = 30
NEAR_EXPIRY_SECONDS = 10 * 60
DEFAULT_TOKEN_FILE = "token.txt"
DEFAULT_USER_AGENT = "Mozilla/5.0"


class ProConnectClient:
    """Small GET-only ProConnect client with request tracing."""

    def __init__(
        self,
        base_url: str,
        bearer_token: str,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self.bearer_token = normalize_bearer_token(bearer_token)
        self.extra_headers = dict(extra_headers or {})
        self.http_calls: List[Dict[str, Any]] = []

    def get_account_by_id(self, account_id: str) -> Dict[str, Any]:
        endpoint = f"/api/accounts/{account_id}"
        return self._request_json(endpoint)

    def search_prospects(self, search_text: str) -> Dict[str, Any]:
        endpoint = "/api/prospects"
        params = {"search": f"'{search_text}'"}
        return self._request_json(endpoint, params=params)

    def get_org_chart(
        self,
        zoom_info_account_id: str,
        department: str,
        sfdc_job_function: str,
        page: Optional[int] = None,
        size: Optional[int] = None,
    ) -> Dict[str, Any]:
        endpoint = "/api/OrgChart"
        params: Dict[str, Any] = {
            "zoomInfoAccountId": zoom_info_account_id,
            "department": department,
            "sfdcJobFunction": sfdc_job_function,
        }
        if page is not None:
            params["page"] = page
        if size is not None:
            params["size"] = size
        return self._request_json(endpoint, params=params)

    def get_user(self) -> Dict[str, Any]:
        endpoint = "/api/user"
        return self._request_json(endpoint)

    def get_endpoint(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        retry_on_5xx: int = 0,
        retry_delay_seconds: float = 0.25,
        stop_on_auth: bool = False,
    ) -> Dict[str, Any]:
        """Generic GET with bounded retries and optional auth short-circuit."""
        last_response: Dict[str, Any] = {
            "success": False,
            "status_code": None,
            "data": {},
            "error": "No request attempted.",
            "url": None,
            "elapsed_ms": 0,
            "attempts": 0,
        }

        max_attempts = max(int(retry_on_5xx), 0) + 1
        for attempt in range(max_attempts):
            response = self._request_json(endpoint, params=params)
            response["attempts"] = attempt + 1
            last_response = response

            status_code = response.get("status_code")
            if stop_on_auth and status_code in {401, 403}:
                response["auth_blocked"] = True
                return response

            if isinstance(status_code, int) and status_code >= 500 and attempt < max_attempts - 1:
                time.sleep(retry_delay_seconds * (attempt + 1))
                continue

            return response

        return last_response

    def _request_json(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = urljoin(self.base_url, endpoint.lstrip("/"))
        if params:
            query = urlencode(params, doseq=True, safe="'()")
            url = f"{url}?{query}"

        headers = self._build_headers()
        request = Request(url=url, method="GET", headers=headers)

        status_code: Optional[int] = None
        parsed_data: Any = None
        error_message: Optional[str] = None
        raw_text = ""
        started = time.time()

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                status_code = int(response.getcode())
                raw_bytes = response.read()
                raw_text = raw_bytes.decode("utf-8", errors="replace")
                parsed_data = _parse_json_or_text(raw_text)
        except HTTPError as exc:
            status_code = int(exc.code)
            raw_text = exc.read().decode("utf-8", errors="replace")
            parsed_data = _parse_json_or_text(raw_text)
            error_message = f"HTTP {status_code}"
            if status_code in {401, 403}:
                error_detail = _extract_error_detail(parsed_data)
                if error_detail:
                    error_message = f"{error_message}: {error_detail}"
                else:
                    error_message = f"{error_message}: authorization failed"
        except URLError as exc:
            error_message = f"Network error: {exc.reason}"
        except Exception as exc:  # pragma: no cover - defensive
            error_message = f"Unexpected error: {exc}"

        elapsed_ms = int((time.time() - started) * 1000)
        success = bool(status_code is not None and 200 <= status_code < 300)

        trace = {
            "method": "GET",
            "endpoint": endpoint,
            "url": url,
            "status_code": status_code,
            "success": success,
            "elapsed_ms": elapsed_ms,
            "error": error_message,
        }
        self.http_calls.append(trace)

        return {
            "success": success,
            "status_code": status_code,
            "data": parsed_data,
            "error": error_message,
            "url": url,
            "elapsed_ms": elapsed_ms,
        }

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Authorization": self.bearer_token,
            "User-Agent": DEFAULT_USER_AGENT,
        }
        for key, value in self.extra_headers.items():
            if key.lower() == "authorization":
                continue
            headers[key] = value
        return headers


def resolve_bearer_token(cli_token: Optional[str], token_file: Optional[str] = None) -> Tuple[str, str]:
    """Resolve token by priority: CLI, env, token file, secure prompt."""
    if cli_token and cli_token.strip():
        return normalize_bearer_token(cli_token), "cli"

    env_token = os.getenv("PROCONNECT_BEARER_TOKEN")
    if env_token and env_token.strip():
        return normalize_bearer_token(env_token), "env"

    search_paths: List[Path] = []
    if token_file:
        search_paths.append(Path(token_file).expanduser())
    else:
        search_paths.append(Path.cwd() / DEFAULT_TOKEN_FILE)
        search_paths.append(Path(__file__).resolve().parent / DEFAULT_TOKEN_FILE)

    for path in search_paths:
        if path.exists():
            from_file = read_token_from_file(path)
            if from_file:
                return normalize_bearer_token(from_file), f"file:{path}"

    if token_file:
        raise FileNotFoundError(f"Token file not found: {token_file}")

    pasted = getpass.getpass("Paste ProConnect bearer token (input hidden): ").strip()
    if not pasted:
        raise ValueError("No bearer token provided.")
    return normalize_bearer_token(pasted), "prompt"


def normalize_bearer_token(token: str) -> str:
    token = (token or "").strip()
    if not token:
        raise ValueError("Bearer token is empty.")

    if token.lower().startswith("bearer "):
        raw = token[7:].strip()
    else:
        raw = token

    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        raw = raw[1:-1].strip()
    if raw.startswith("<") and raw.endswith(">"):
        raw = raw[1:-1].strip()

    # Token strings should not contain whitespace; collapse accidental wraps/pastes.
    raw = "".join(raw.split())

    if not raw:
        raise ValueError("Bearer token is invalid.")

    return f"Bearer {raw}"


def decode_jwt_payload_no_verify(token: str) -> Dict[str, Any]:
    """Decode JWT payload without verification for local expiry warnings."""
    raw = strip_bearer_prefix(token)
    parts = raw.split(".")
    if len(parts) < 2:
        return {"decode_error": "Token is not JWT-like."}

    payload_b64 = parts[1]
    padding = "=" * ((4 - (len(payload_b64) % 4)) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload_b64 + padding)
        payload = json.loads(decoded.decode("utf-8", errors="replace"))
        if not isinstance(payload, dict):
            return {"decode_error": "Decoded JWT payload is not a JSON object."}
        return payload
    except Exception as exc:  # pragma: no cover - defensive
        return {"decode_error": f"Could not decode JWT payload: {exc}"}


def token_health_summary(token: str, now_epoch: Optional[int] = None) -> Dict[str, Any]:
    payload = decode_jwt_payload_no_verify(token)
    now_ts = int(now_epoch if now_epoch is not None else time.time())

    result: Dict[str, Any] = {
        "token_preview": redact_token(token),
        "issued_at_utc": None,
        "expires_at_utc": None,
        "seconds_to_expiry": None,
        "is_expired": None,
        "is_near_expiry": None,
        "warnings": [],
    }

    if "decode_error" in payload:
        result["warnings"].append(payload["decode_error"])
        return result

    iat = payload.get("iat")
    exp = payload.get("exp")

    if isinstance(iat, int):
        result["issued_at_utc"] = datetime.fromtimestamp(iat, tz=timezone.utc).isoformat()
    if isinstance(exp, int):
        result["expires_at_utc"] = datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()
        remaining = exp - now_ts
        result["seconds_to_expiry"] = remaining
        result["is_expired"] = remaining <= 0
        result["is_near_expiry"] = 0 < remaining <= NEAR_EXPIRY_SECONDS

        if remaining <= 0:
            result["warnings"].append("Token is expired.")
        elif remaining <= NEAR_EXPIRY_SECONDS:
            result["warnings"].append("Token is near expiry (<= 10 minutes).")
    else:
        result["warnings"].append("Token does not include an integer 'exp' claim.")

    return result


def load_extra_headers(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}

    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Extra headers file not found: {file_path}")

    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Extra headers file must be a JSON object of header-value pairs.")

    headers: Dict[str, str] = {}
    for key, value in payload.items():
        headers[str(key)] = str(value)
    return headers


def read_token_from_file(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    if not raw:
        raise ValueError(f"Token file is empty: {path}")
    return raw.strip()


def write_json_artifact(output_dir: str, prefix: str, payload: Dict[str, Any]) -> str:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    timestamp_slug = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = payload.get("run_id", "unknown")
    filename = f"{prefix}_{timestamp_slug}_{run_id}.json"
    file_path = destination / filename
    file_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    return str(file_path)


def default_output_dir() -> str:
    return str(Path(__file__).resolve().parent / "output" / "proconnect_runs")


def make_run_id() -> str:
    return uuid.uuid4().hex[:12]


def utc_timestamp() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def redact_token(token: str) -> str:
    raw = strip_bearer_prefix(token)
    if len(raw) <= 12:
        return "<redacted>"
    return f"{raw[:6]}...{raw[-6:]}"


def strip_bearer_prefix(token: str) -> str:
    token = (token or "").strip()
    if token.lower().startswith("bearer "):
        return token[7:].strip()
    return token


def print_check_table(rows: Iterable[Dict[str, Any]]) -> None:
    rows_list = list(rows)
    if not rows_list:
        print("No checks executed.")
        return

    headers = ["Check", "Status", "HTTP", "Details"]
    matrix: List[List[str]] = []
    for row in rows_list:
        matrix.append(
            [
                str(row.get("check", "")),
                str(row.get("status", "")),
                str(row.get("http", "")),
                str(row.get("details", "")),
            ]
        )

    widths = [len(h) for h in headers]
    for entry in matrix:
        for idx, cell in enumerate(entry):
            widths[idx] = max(widths[idx], len(cell))

    def _render_line(values: List[str]) -> str:
        return " | ".join(values[i].ljust(widths[i]) for i in range(len(values)))

    print(_render_line(headers))
    print("-+-".join("-" * w for w in widths))
    for entry in matrix:
        print(_render_line(entry))


def _parse_json_or_text(text: str) -> Any:
    content = (text or "").strip()
    if not content:
        return {}
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"raw_text": content}


def _extract_error_detail(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        for key in ("message", "error_description", "error", "detail", "title"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None
